""" DatasetIndex """

import os
import glob
import numpy as np
from .base import Baseset


class DatasetIndex(Baseset):
    """ Stores an index for a dataset
    The index should be 1-d array-like, e.g. numpy array, pandas Series, etc.
    """
    @staticmethod
    def build_index(index):
        """ Check index type and structure """
        if callable(index):
            _index = index()
        else:
            _index = index

        if isinstance(_index, DatasetIndex):
            _index = _index.index
        else:
            # index should allow for advance indexing (i.e. subsetting)
            try:
                _ = _index[[0]]
            except TypeError:
                _index = np.asarray(_index)
            except IndexError:
                raise ValueError("Index cannot be empty")

        if len(_index.shape) > 1:
            raise TypeError("Index should be 1-dimensional")

        return _index


    def subset_by_pos(self, pos):
        """ Return subset of index by given positions in the index """
        return self.index[pos]


    def cv_split(self, shares=0.8, shuffle=False):
        """ Split index into train, test and validation subsets
        Shuffles index if necessary.
        Subsets are available as .train, .test and .validation respectively

        Usage:
           # split into train / test in 80/20 ratio
           di.cv_split()
           # split into train / test / validation in 60/30/10 ratio
           di.cv_split([0.6, 0.3])
           # split into train / test / validation in 50/30/20 ratio
           di.cv_split([0.5, 0.3, 0.2])
        """
        _, test_share, valid_share = self.calc_cv_split(shares)

        # TODO: make a view not copy if not shuffled
        order = np.arange(len(self))
        if shuffle:
            np.random.shuffle(order)

        if valid_share > 0:
            validation_pos = order[:valid_share]
            self.validation = DatasetIndex(self.subset_by_pos(validation_pos))
        if test_share > 0:
            test_pos = order[valid_share : valid_share + test_share]
            self.test = DatasetIndex(self.subset_by_pos(test_pos))
        train_pos = order[valid_share + test_share:]
        self.train = DatasetIndex(self.subset_by_pos(train_pos))


    def next_batch(self, batch_size, shuffle=False, one_pass=False):
        """ Return next batch """
        num_items = len(self)

        # TODO: make a view not copy whenever possible
        if self._order is None:
            self._order = np.arange(num_items)
            if shuffle:
                np.random.shuffle(self._order)

        rest_items = None
        if self._start_index + batch_size >= num_items:
            rest_items = np.copy(self._order[self._start_index:])
            rest_of_batch = self._start_index + batch_size - num_items
            self._start_index = 0
            self._n_epochs += 1
            if shuffle:
                np.random.shuffle(self._order)
        else:
            rest_of_batch = batch_size

        new_items = self._order[self._start_index : self._start_index + rest_of_batch]
        # TODO: concat not only numpy arrays
        if rest_items is None:
            batch_items = new_items
        else:
            batch_items = np.concatenate((rest_items, new_items))

        if one_pass and rest_items is not None:
            return self.create_batch(rest_items, pos=True)
        else:
            self._start_index += rest_of_batch
            return self.create_batch(batch_items, pos=True)


    def gen_batch(self, batch_size, shuffle=False, one_pass=False):
        """ Generate batches """
        self._start_index = 0
        self._order = None
        _n_epochs = self._n_epochs
        while True:
            if one_pass and self._n_epochs > _n_epochs:
                raise StopIteration()
            else:
                yield self.next_batch(batch_size, shuffle, one_pass)


    def create_batch(self, batch_indices, pos=True):
        """ Create a batch from given indices
            if pos is False then batch_indices contains the value of indices
            which should be included in the batch (so expected batch is just the very same batch_indices)
            otherwise batch_indices contains positions in the index
        """
        if pos:
            batch = self.subset_by_pos(batch_indices)
        else:
            batch = batch_indices
        return batch


class FilesIndex(DatasetIndex):
    """ Index with the list of files or directories with the given path pattern

        Usage:
        Create sorted index of files in a directory:
        fi = FilesIndex('/path/to/data/files/*', sort=True)
        Create unsorted index of directories through all subdirectories:
        fi = FilesIndex('/path/to/data/archive*/patient*', dirs=True)
    """
    @staticmethod
    def build_index(path, dirs=False, sort=False):    # pylint: disable=arguments-differ
        """ Generate index from path """
        check_fn = os.path.isdir if dirs else os.path.isfile
        pathlist = glob.iglob(path)
        _index = np.asarray([os.path.basename(fname) for fname in pathlist if check_fn(fname)])
        if sort:
            _index = np.sort(_index)
        return _index
