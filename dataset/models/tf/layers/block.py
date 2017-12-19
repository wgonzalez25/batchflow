import logging
import numpy as np
import tensorflow as tf

from .core import mip, flatten, alpha_dropout
from .conv import conv_transpose, separable_conv
from .pooling import pooling, global_pooling

def _conv_block(inputs, layout='', filters=0, kernel_size=3, name=None,
                strides=1, padding='same', data_format='channels_last', dilation_rate=1, depth_multiplier=1,
                activation=tf.nn.relu, pool_size=2, pool_strides=2, dropout_rate=0., is_training=True, 
                layout_dict=None, **kwargs):
    
    ND_LAYERS = {
        'activation': None,
        'residual_start': None,
        'residual_end': None,
        'dense': tf.layers.dense,
        'conv': [tf.layers.conv1d, tf.layers.conv2d, tf.layers.conv3d],
        'transposed_conv': conv_transpose,
        'separable_conv':separable_conv,
        'pooling': pooling,
        'global_pooling': global_pooling,
        'batch_norm': tf.layers.batch_normalization,
        'dropout': tf.layers.dropout,
        'alpha_dropout': alpha_dropout,
        'mip': mip
    }

    C_LAYERS = {
        'a': 'activation',
        'R': 'residual_start',
        '+': 'residual_end',
        'f': 'dense',
        'c': 'conv',
        't': 'transposed_conv',
        's': 'separable_conv',
        'p': 'pooling',
        'v': 'pooling',
        'P': 'global_pooling',
        'V': 'global_pooling',
        'n': 'batch_norm',
        'd': 'dropout',
        'D': 'alpha_dropout',
        'm': 'mip',
    }


    if layout_dict is not None:
        ND_LAYERS = {**ND_LAYERS, **layout_dict[0]}
        C_LAYERS = {**C_LAYERS, **layout_dict[1]} 
    _LAYERS_KEYS = str(list(C_LAYERS.keys()))
    _GROUP_KEYS = (
        _LAYERS_KEYS
        .replace('t', 'c')
        .replace('s', 'c')
        .replace('v', 'p')
        .replace('V', 'P')
        .replace('D', 'd')
        .replace('B', 'b')
        .replace('N', 'b')
    )
    C_GROUPS = dict(zip(_LAYERS_KEYS, _GROUP_KEYS))

    def _get_layer_fn(fn, dim):
        f = ND_LAYERS[fn]
        return f if callable(f) or f is None else f[dim-1]

    def _unpack_args(args, layer_no, layers_max):
        new_args = {}
        for arg in args:
            if isinstance(args[arg], list) and layers_max > 1:
                arg_value = args[arg][layer_no]
            else:
                arg_value = args[arg]
            new_args.update({arg: arg_value})

        return new_args

    layout = layout or ''
    layout = layout.replace(' ', '')
    if len(layout) == 0:
        logging.warning('conv_block: layout is empty, so there is nothing to do, just returning inputs.')
        return inputs

    dim = inputs.shape.ndims - 2
    if not isinstance(dim, int) or dim > 3:
        raise ValueError("Number of dimensions of the inputs tensor should be 1, 2 or 3, but given %d" % dim)

    context = None
    if name is not None:
        context = tf.variable_scope(name, reuse=kwargs.get('reuse'))
        context.__enter__()

    layout_dict = {}
    for layer in layout:
        if C_GROUPS[layer] not in layout_dict:
            layout_dict[C_GROUPS[layer]] = [-1, 0]
        layout_dict[C_GROUPS[layer]][1] += 1

    residuals = []
    tensor = inputs
    for i, layer in enumerate(layout):

        layout_dict[C_GROUPS[layer]][0] += 1
        layer_name = C_LAYERS[layer]
        layer_fn = _get_layer_fn(layer_name, dim)

        if layer == 'a':
            args = dict(activation=activation)
            layer_fn = _unpack_args(args, *layout_dict[C_GROUPS[layer]])['activation']
            if layer_fn is not None:
                tensor = layer_fn(tensor)
        elif layer == 'R':
            residuals += [tensor]
        elif layer == '+':
            tensor = tensor + residuals[-1]
            residuals = residuals[:-1]
        else:
            layer_args = kwargs.get(layer_name, {})
            skip_layer = layer_args is None or layer_args is False or \
                         isinstance(layer_args, dict) and layer_args.pop('disable', False)

            if skip_layer:
                pass
            elif layer == 'f':
                if tensor.shape.ndims > 2:
                    tensor = flatten(tensor)
                units = kwargs.get('units')
                if units is None:
                    raise ValueError('units cannot be None if layout includes dense layers')
                args = dict(units=units)

            elif layer == 'c':
                args = dict(filters=filters, kernel_size=kernel_size, strides=strides, padding=padding,
                            data_format=data_format, dilation_rate=dilation_rate)
                if filters is None or filters == 0:
                    raise ValueError('filters cannot be None or 0 if layout includes convolutional layers')

            elif layer == 's':
                args = dict(filters=filters, kernel_size=kernel_size, strides=strides, padding=padding,
                            data_format=data_format, dilation_rate=dilation_rate, depth_multiplier=depth_multiplier)
                if filters is None or filters == 0:
                    raise ValueError('filters cannot be None or 0 if layout includes convolutional layers')

            elif layer == 't':
                args = dict(filters=filters, kernel_size=kernel_size, strides=strides, padding=padding,
                            data_format=data_format)
                if filters is None or filters == 0:
                    raise ValueError('filters cannot be None or 0 if layout includes convolutional layers')

            elif layer == 'n':
                axis = -1 if data_format == 'channels_last' else 1
                args = dict(fused=True, axis=axis, training=is_training)

            elif C_GROUPS[layer] == 'p':
                if layer == 'v':
                    pool_op = 'mean'
                else:
                    pool_op = kwargs.pop('pool_op', 'max')
                args = dict(pool_op=pool_op, pool_size=pool_size, strides=pool_strides, padding=padding,
                            data_format=data_format)


            elif layer in ['d', 'D']:
                if dropout_rate:
                    args = dict(rate=dropout_rate, training=is_training)
                else:
                    skip_layer = True

            elif C_GROUPS[layer] == 'P':
                if layer == 'P':
                    pool_op = kwargs.pop('global_pool_op', 'max')
                elif layer == 'V':
                    pool_op = 'mean'
                args = dict(pool_op=pool_op, data_format=data_format)

            elif layer == 'm':
                args = dict(data_format=data_format)

            elif layer in ['b', 'B', 'N', 'X']:
                args = dict(factor=kwargs.get('factor'), data_format=data_format)

            if not skip_layer:
                args = {**args, **layer_args}
                args = _unpack_args(args, *layout_dict[C_GROUPS[layer]])

                with tf.variable_scope('layer-%d' % i):
                    tensor = layer_fn(tensor, **args)

    if context is not None:
        context.__exit__(None, None, None)

    return tensor