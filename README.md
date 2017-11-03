# Dataset

`Dataset` helps you conveniently work with random or sequential batches of your data
and define data processing and machine learning workflows even for datasets that do not fit into memory.

For more details see [the documentation and tutorials](https://analysiscenter.github.io/dataset/).

Main features:
- flexible batch generaton
- deterministic and stochastic pipelines
- datasets and pipelines joins and merges
- data processing actions
- flexible model configuration
- within batch parallelism
- batch prefetching
- ready to use ML models and proven NN architectures
- convenient layers and helper functions to build custom models.

## Basic usage

```python
my_workflow = my_dataset.pipeline()
              .load('/some/path')
              .do_something()
              .do_something_else()
              .some_additional_action()
              .save('/to/other/path')
```
The trick here is that all the processing actions are lazy. They are not executed until their results are needed, e.g. when you request a preprocessed batch:
```python
my_workflow.run(BATCH_SIZE, shuffle=True, n_epochs=5)
```
or
```python
for batch in my_workflow.gen_batch(BATCH_SIZE, shuffle=True, n_epochs=5):
    # only now the actions are fired and data is being changed with the workflow defined earlier
    # actions are executed one by one and here you get a fully processed batch
```
or
```python
NUM_ITERS = 1000
for i in range(NUM_ITERS):
    processed_batch = my_workflow.next_batch(BATCH_SIZE, shuffle=True, n_epochs=None)
    # only now the actions are fired and data is changed with the workflow defined earlier
    # actions are executed one by one and here you get a fully processed batch
```

For more advanced cases and detailed API see [the documentation](https://analysiscenter.github.io/dataset/).


## Installation

> `Dataset` module is in the beta stage. Your suggestions and improvements are very welcome.

> `Dataset` supports python 3.5 or higher.

### Python package
With modern [pipenv](https://docs.pipenv.org/)
```
pipenv install git+https://github.com/analysiscenter/dataset.git
```

With old-fashioned [pip](https://pip.pypa.io/en/stable/)
```
pip3 install git+https://github.com/analysiscenter/dataset.git#egg=dataset
```

After that just import `dataset`:
```python
import dataset as ds
```

### Git submodule
In many cases it might be more convenient to install `dataset` as a submodule in your project repository than as a python package.
```
git submodule add https://github.com/analysiscenter/dataset.git
git submodule init
git submodule update
```

If your python file is located in another directory, you might need to add a path to `dataset`:
```python
import sys
sys.path.insert(0, "/path/to/dataset/dataset")
import dataset as ds
```

Local import is also possible:
```python
import .dataset.dataset as ds
```

Note the double `dataset` in import - it's not a typo.

What is great about using a submodule that every commit in your project can be linked to its own version of a submodule.
This is extremely convenient in a fast paced research environment.
