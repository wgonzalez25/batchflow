""" Contains class for ResNet """
import numpy as np
import tensorflow as tf

from . import TFModel
from .layers import conv_block


class ResNet(TFModel):
    """ The base ResNet model

    References
    ----------
    .. Kaiming He et al. "Deep Residual Learning for Image Recognition"
       Arxiv.org, `<https://arxiv.org/abs/1512.03385>`_

    .. Sergey Zagoruyko, Nikos Komodakis. "Wide Residual Networks"
       Arxiv.org, `<https://arxiv.org/abs/1605.07146>`_

    .. Xie S. et al. "Aggregated Residual Transformations for Deep Neural Networks"
       Arxiv.org, `<https://arxiv.org/abs/1611.05431>`_

    ** Configuration **

    inputs : dict
        dict with keys 'images' and 'masks' (see :meth:`._make_inputs`)

    input_block : dict

    filters : int
        number of filters in the first block (default=64)

    body : dict
        num_blocks : list of int
            number of blocks in each group with the same number of filters.
        filters : list of int
            number of filters in each group (default=[64, 128, 256, 512])

    block : dict
        bottleneck : bool
            whether to use bottleneck blocks (1x1,3x3,1x1) or simple (3x3,3x3)
        bottleneck_factor : int
            filter shrinking factor in a bottleneck block (default=4)
        width_factor : int
            widening factor to make WideResNet (default=4)
        se_block : bool
            whether to use squeeze-and-excitation blocks
        se_factor : int
            squeeze-and-excitation channels ratio
        resnext : bool
            whether to use aggregated ResNeXt block
        resnext_factor : int
            the number of aggregations in ResNeXt block (default=32)
    """
    @classmethod
    def _default_config(cls):
        config = TFModel._default_config()
        config['input_block'].update(dict(layout='cnap', filters=64, kernel_size=7, strides=2,
                                          pool_size=3, pool_strides=2))

        config['block'] = dict(activation=tf.nn.relu, bottleneck=0, bottleneck_factor=4, width_factor=1,
                               resnext=False, resnext_factor=32,
                               se_block=False, se_factor=16)

        config['head'].update(dict(layout='Vdf', dropout_rate=.4, units=list()))

        return config

    def _build_config(self, names=None):
        names = names if names else ['images', 'labels']
        config = super()._build_config(names)

        filters = self.get_from_config('filters', 64)

        config['common']['data_format'] = self.data_format('images')
        config['input_block']['inputs'] = self.inputs['images']

        config['body']['filters'] = 2 ** np.arange(len(config['body']['filters'])) * filters * config['block']['width_factor']

        config['head']['units'] = self.num_classes('labels')

        return config


    @classmethod
    def body(cls, inputs, name='body', **kwargs):
        """ Base layers

        Parameters
        ----------
        inputs : tf.Tensor
            input tensor
        filters : list of int
            number of filters in each block group
        num_blocks : list of int
            number of blocks in each group
        bottleneck : bool
            whether to use a simple or bottleneck block
        bottleneck_factor : int
            filter number multiplier for a bottleneck block
        name : str
            scope name

        Returns
        -------
        tf.Tensor
        """
        kwargs = cls.fill_params('body', **kwargs)
        filters = kwargs.pop('filters')

        with tf.variable_scope(name):
            x = inputs
            for i, n_blocks in enumerate(kwargs['num_blocks']):
                with tf.variable_scope('block-%d' % i):
                    for block in range(n_blocks):
                        strides = 2 if i > 0 and block == 0 else 1
                        x = cls.block(x, filters=filters[i], name='layer-%d' % block, strides=strides, **kwargs)
        return x

    @classmethod
    def double_block(cls, inputs, name='double_block', strides=1, **kwargs):
        """ Two ResNet blocks one after another

        Parameters
        ----------
        inputs : tf.Tensor
            input tensor
        filters : int
            number of output filters
        name : str
            scope name

        Returns
        -------
        tf.Tensor
        """
        with tf.variable_scope(name):
            x = cls.block(inputs, name='block-1', strides=strides, **kwargs)
            x = cls.block(x, name='block-2', strides=1, **kwargs)
        return x

    @classmethod
    def block(cls, inputs, name='block', **kwargs):
        """ A network building block

        Parameters
        ----------

        inputs : tf.Tensor
            input tensor
        filters : int
            number of output filters
        resnext : bool
            whether to use a usuall or aggregated ResNeXt block
        resnext_factor : int
            cardinality for ResNeXt block
        bottleneck : bool
            whether to use a simple or bottleneck block
        bottleneck_factor : int
            the filters nultiplier in the bottleneck block
        se_block : bool
            whether to include squeeze and excitation block
        se_factor : int
            se block ratio
        name : str
            scope name

        Returns
        -------
        tf.Tensor
        """
        kwargs = cls.fill_params('block', **kwargs)
        filters = kwargs.pop('filters')
        bottleneck = kwargs.pop('bottleneck')
        bottleneck_factor = kwargs.pop('bottleneck_factor')
        resnext_factor = kwargs.pop('resnext_factor')
        strides = kwargs.pop('strides')
        se_block = kwargs.pop('se_block')
        se_factor = kwargs.pop('se_factor')
        activation = kwargs.get('activation')

        with tf.variable_scope(name):
            if kwargs['resnext']:
                x = cls.next_sub_block(inputs, filters, bottleneck, resnext_factor, name='sub',
                                       strides=strides, **kwargs)
            else:
                x = cls.sub_block(inputs, filters, bottleneck, bottleneck_factor, name='sub',
                                  strides=strides, **kwargs)

            data_format = kwargs.get('data_format')
            inputs_channels = cls.channels_shape(inputs, data_format)
            x_channels = cls.channels_shape(x, data_format)

            if inputs_channels != x_channels or strides > 1:
                shortcut = conv_block(inputs, x_channels, 1, 'c', name='shortcut', strides=strides, **kwargs)
            else:
                shortcut = inputs

            if se_block:
                x = cls.se_block(x, se_factor, **kwargs)

            x = x + shortcut

            if activation:
                x = activation(x)

            x = tf.identity(x, name='output')

        return x

    @classmethod
    def sub_block(cls, inputs, filters, bottleneck, bottleneck_factor, name, strides=1, **kwargs):
        """ ResNet convolution block

        Parameters
        ----------

        inputs : tf.Tensor
            input tensor
        filters : int
            number of output filters
        bottleneck : bool
            whether to use a simple or a bottleneck block
        bottleneck_factor : int
            filter count scaling factor
        name : str
            scope name

        Returns
        -------
        tf.Tensor
        """
        if bottleneck:
            x = cls.bottleneck_block(inputs, filters, bottleneck_factor, name, strides=strides, **kwargs)
        else:
            x = cls.simple_block(inputs, filters, name, strides=strides, **kwargs)
        return x

    @classmethod
    def simple_block(cls, inputs, filters, name, strides, **kwargs):
        """ A simple residual block with two 3x3 convolutions

        Parameters
        ----------

        inputs : tf.Tensor
            input tensor
        filters : int
            number of filters
        name : str
            scope name

        Returns
        -------
        tf.Tensor
        """
        return conv_block(inputs, filters, 3, layout='cnacn', name=name, strides=[strides, 1], **kwargs)


    @classmethod
    def bottleneck_block(cls, inputs, filters, bottleneck_factor, name, strides, **kwargs):
        """ A stack of 1x1, 3x3, 1x1 convolutions

        Parameters
        ----------

        inputs : tf.Tensor
            input tensor
        filters : int
            number of filters in the first two convolutions
        bottleneck_factor : int
            scale factor for the number of filters

        Returns
        -------
        tf.Tensor
        """
        layout = kwargs.pop('layout', None) or 'cna'
        x = conv_block(inputs, [filters, filters, filters * bottleneck_factor], [1, 3, 1],
                       layout*3, name=name, strides=[strides, 1, 1], **kwargs)
        return x

    @classmethod
    def next_sub_block(cls, inputs, filters, bottleneck, resnext_factor, name, **kwargs):
        """ ResNeXt convolution block

        Parameters
        ----------
        inputs : tf.Tensor
            input tensor
        filters : int
            number of output filters
        bottleneck : bool
            whether to use a simple or a bottleneck block
        resnext_factor : int
            cardinality for ResNeXt model
        name : str
            scope name

        Returns
        -------
        tf.Tensor
        """
        sub_blocks = []
        with tf.variable_scope(name):
            for i in range(resnext_factor):
                with tf.variable_scope('next_sub_block-%d' % i):
                    if bottleneck:
                        x = cls.bottleneck_block(inputs, 4, bottleneck_factor=filters//4, name='conv', **kwargs)
                    else:
                        x = cls.simple_block(inputs, [4, filters], name='conv', **kwargs)
                    sub_blocks.append(x)
            x = tf.add_n(sub_blocks)
        return x

    @classmethod
    def se_block(cls, inputs, ratio, name='se', **kwargs):
        """ Squeeze and excitation block

        Parameters
        ----------
        inputs : tf.Tensor
            input tensor
        ratio : int
            squeeze ratio for the number of filters

        Returns
        -------
        tf.Tensor
        """
        with tf.variable_scope(name):
            data_format = kwargs.get('data_format')
            in_filters = cls.channels_shape(inputs, data_format)
            x = conv_block(inputs, layout='Vfafa', units=[in_filters//ratio, in_filters], name='se',
                           **{**kwargs, 'activation': [tf.nn.relu, tf.nn.sigmoid]})

            shape = [-1] + [1] * (len(cls.spatial_shape(inputs, data_format)) + 1)
            axis = cls.channels_axis(data_format)
            shape[axis] = in_filters
            scale = tf.reshape(x, shape)
            x = inputs * scale
        return x



class ResNet18(ResNet):
    """ The original ResNet-18 architecture

    References
    ----------
    .. Kaiming He et al. "Deep Residual Learning for Image Recognition"
       Arxiv.org, `<https://arxiv.org/abs/1512.03385>`_
    """
    @classmethod
    def _default_config(cls):
        config = ResNet._default_config()

        filters = 64   # number of filters in the first block
        config['body']['num_blocks'] = [2, 2, 2, 2]
        config['body']['filters'] = 2 ** np.arange(len(config['body']['num_blocks'])) * filters \
                                    * config['block']['width_factor']
        config['block']['bottleneck'] = False
        return config


class ResNet34(ResNet):
    """ The original ResNet-34 architecture

    References
    ----------
    .. Kaiming He et al. "Deep Residual Learning for Image Recognition"
       Arxiv.org, `<https://arxiv.org/abs/1512.03385>`_
    """
    @classmethod
    def _default_config(cls):
        config = ResNet._default_config()

        config['body']['num_blocks'] = [3, 4, 6, 3]
        filters = 64   # number of filters in the first block
        config['body']['filters'] = 2 ** np.arange(len(config['body']['num_blocks'])) * filters \
                                    * config['block']['width_factor']
        config['block']['bottleneck'] = False
        return config


class ResNet50(ResNet):
    """ The original ResNet-50 architecture

    References
    ----------
    .. Kaiming He et al. "Deep Residual Learning for Image Recognition"
       Arxiv.org, `<https://arxiv.org/abs/1512.03385>`_
    """
    @classmethod
    def _default_config(cls):
        config = ResNet34._default_config()
        config['block']['bottleneck'] = True
        return config


class ResNet101(ResNet):
    """ The original ResNet-101 architecture

    References
    ----------
    .. Kaiming He et al. "Deep Residual Learning for Image Recognition"
       Arxiv.org, `<https://arxiv.org/abs/1512.03385>`_
    """
    @classmethod
    def _default_config(cls):
        config = ResNet._default_config()

        filters = 64   # number of filters in the first block
        config['body']['num_blocks'] = [3, 4, 23, 3]
        config['body']['filters'] = 2 ** np.arange(len(config['body']['num_blocks'])) * filters \
                                    * config['block']['width_factor']
        config['block']['bottleneck'] = True
        return config


class ResNet152(ResNet):
    """ The original ResNet-152 architecture

    References
    ----------
    .. Kaiming He et al. "Deep Residual Learning for Image Recognition"
       Arxiv.org, `<https://arxiv.org/abs/1512.03385>`_
    """
    @classmethod
    def _default_config(cls):
        config = ResNet._default_config()

        filters = 64   # number of filters in the first block
        config['body']['num_blocks'] = [3, 8, 63, 3]
        config['body']['filters'] = 2 ** np.arange(len(config['body']['num_blocks'])) * filters \
                                    * config['block']['width_factor']
        config['block']['bottleneck'] = True
        return config
