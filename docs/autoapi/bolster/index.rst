bolster
=======

.. py:module:: bolster

.. autoapi-nested-parse::

   Bolster - A personal collection of Python utilities and data sources.

   A grab bag of handy functions for working with Northern Ireland data,
   basic stats operations, and general data science tasks. Built for personal
   projects and exploration.

   What's in here:
       - data_sources: NI water quality, house prices, cinema listings, etc.
       - stats: Basic data frame operations and distribution fitting
       - utils: Web scraping helpers, decorators, AWS/Azure bits
       - cli: Command line tools for the data sources

   Quick examples:

       >>> from bolster.data_sources import ni_water
       >>> quality_data = ni_water.get_water_quality_by_zone('BALM')

       >>> from bolster.stats import add_totals
       >>> add_totals(my_dataframe)  # adds row/column totals

   Author: Andrew Bolster



Submodules
----------

.. toctree::
   :maxdepth: 1

   /autoapi/bolster/cli/index
   /autoapi/bolster/data_sources/index
   /autoapi/bolster/stats/index
   /autoapi/bolster/utils/index


Attributes
----------

.. autoapisummary::

   bolster.__author__
   bolster.__email__
   bolster.__version__
   bolster.logger


Exceptions
----------

.. autoapisummary::

   bolster.MultipleErrors


Classes
-------

.. autoapisummary::

   bolster.memoize


Functions
---------

.. autoapisummary::

   bolster.always
   bolster.poolmap
   bolster.batch
   bolster.chunks
   bolster.arg_exception_logger
   bolster.backoff
   bolster.tag_gen
   bolster.exceptional_executor
   bolster.working_directory
   bolster.compress_for_relay
   bolster.decompress_from_relay
   bolster.pretty_print_request
   bolster.get_recursively
   bolster.transform_
   bolster.diff
   bolster.aggregate
   bolster.breadth
   bolster.depth
   bolster.set_keys
   bolster.keys_at
   bolster.items_at
   bolster.leaves
   bolster.leaf_paths
   bolster.flatten_dict
   bolster.uncollect_object
   bolster.dict_concat_safe
   bolster.build_default_mapping_dict_from_keys


Package Contents
----------------

.. py:data:: __author__
   :value: 'Andrew Bolster'


.. py:data:: __email__
   :value: 'andrew.bolster@gmail.com'


.. py:data:: __version__

.. py:data:: logger

.. py:function:: always(x, **kwargs)

   Pointless passthrough replacement for 'always true' filtering

   >>> always('false')
   True
   >>> always(False)
   True
   >>> always(True)
   True


.. py:function:: poolmap(f, iterable, max_workers = None, progress = None, **kwargs)

   Helper function to encapsulate a ThreadPoolExecutor mapped function workflow
   Accepts (assumed to be `tqdm` style) progress monitor callback

   `kwargs` are passed identically to all `f(i)` calls for each i in `iterable`

   :param f: function to map across
   :param iterable:
   :param max_workers: (Default value = None)
   :param progress: (Default value = None)
   :param \*\*kwargs: passed as arguments to f

   Returns:



.. py:function:: batch(seq, n = 1)

   Split a sequence into n-length batches (is still iterable, not list)

   :param seq:
   :param n: (Default value = 1)

   Returns:

   >>> next((b for b in batch(range(10), 2)))
   range(0, 2)
   >>> [b for b in batch(list(range(10)), 2)]
   [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]


.. py:function:: chunks(iterable, size=10)

   Outputs <list> chunks of size N from an iterable (generator)

   :param iterable: param size:
   :param iterable: Iterable:
   :param size: (Default value = 10)

   Returns:

   >>> next((b for b in chunks(range(10), 2)))
   [0, 1]
   >>> [b for b in chunks(list(range(10)), 2)]
   [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]


.. py:function:: arg_exception_logger(func)

   Helper Decorator to provide info on the arguments that cause the exception of a wrapped function

   :param func:

   Returns:



.. py:function:: backoff(exception_to_check = BaseException, tries = 5, delay = 0.2, backoff = 2, logger = logger)

   Retry calling the decorated function using an exponential backoff.

   http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
   original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

   Can't Type-Annotate Exceptions because
   [it's verboten](https://peps.python.org/pep-0484/#exceptions)

   :param exception_to_check: the exception to check. may be a tuple of

   exceptions to check
     tries: number of times to try (not retry) before giving up (Default value = 5)
     delay: initial delay between retries in seconds (Default value = 0.4)
     backoff: backoff multiplier e.g. value of 2 will double the delay
   each retry (Default value = 2)
     logger: logger to use. If None, print (Default value = local utils logger)

   Returns:



.. py:exception:: MultipleErrors(errors=None)

   Bases: :py:obj:`BaseException`


   Exception Class to enable the capturing of multiple exceptions without interrupting control flow, i.e. catch
   the exception, but carry on and report the exceptions at the end.

   E.g.

   .. code-block:: python

       exceptions = MultipleErrors()
       try:
           do_risky_thing_with(this) #raises ValueError
       except:
           exceptions.capture_current_exception()
       try:
           do_other_thing_with(this) #raises AttributeError
       except:
           exceptions.capture_current_exception()
       exceptions.do_raise()



   .. code-block:: none

        Traceback (most recent call last):
           ....
       Value Error

       Traceback (most recent call last):
           ...
       AttributeError


   Initialize self.  See help(type(self)) for accurate signature.


   .. py:attribute:: errors
      :value: []



   .. py:method:: __str__()

      Return str(self).



   .. py:method:: capture_current_exception()

      Gathers exception info from the current context and retains it



   .. py:method:: do_raise()

      Raises itself if it contains any errors



.. py:function:: tag_gen(seq, **kwargs)

   Generator stream that adds a kwargs to each entry yielded

   The below example shows the creation of an empty dict generator where
   tag_gen is used to insert a new key/value (k=1) in each item on the fly

   >>> all([i['k'] == 1 for i in tag_gen(({} for _ in range(4)), k=1)])
   True

   :param seq: param kwargs:
   :param seq: Iterator[Dict]:
   :param \*\*kwargs:


.. py:function:: exceptional_executor(futures, exception_handler=None, timeout=None)

   Generator for concurrent.Futures handling

   When an exception is raised in an executing Future, f.result() called on it's own will raise that
   exception in the parent thread, killing execution and causing loss of 'future local' scope.

   Instead, query the future for it's exception state first, and handle that separately, by default
   by logging it as an exception.


   :param futures:
   :param exception_handler:
   :param timeout:

   Returns:



.. py:function:: working_directory(path)

   Contextmanager that changes working directory and returns to previous on exit.

   :param path: Union[str: Path]:


.. py:function:: compress_for_relay(obj)

   Compress json-serializable object to a gzipped base64 string

   :param obj: return:
   :param obj: Union[List,Dict]:

   >>> decompress_from_relay(compress_for_relay(['test']))
   ['test']

   >>> decompress_from_relay(compress_for_relay({'test':'test'}))
   {'test': 'test'}



.. py:function:: decompress_from_relay(msg)

   Uncompress  gzipped base64 string to a json-serializable object
   ['test']

   :param msg: AnyStr:

   Returns:



.. py:class:: memoize(func)

   Bases: :py:obj:`object`


   cache the return value of a method

   This class is meant to be used as a decorator of methods. The return value
   from a given method invocation will be cached on the instance whose method
   was invoked. All arguments passed to a method decorated with memoize must
   be hashable.

   If a memoized method is invoked directly on its class the result will not
   be cached. Instead the method will be invoked like a static method:

   .. code-block:: python

       class Obj(object):
           @memoize
           def add_to(self, arg):
           return self + arg

       Obj.add_to(1) # not enough arguments
       Obj.add_to(1, 2) # returns 3, result is not cached

   Source: http://code.activestate.com/recipes/577452-a-memoize-decorator-for-instance-methods/

   Augmented with cache hit/miss population Counters



   .. py:attribute:: func


   .. py:method:: __get__(obj, objtype=None)


   .. py:method:: __call__(*args, **kw)


.. py:function:: pretty_print_request(req, expose_auth=False, authentication_header_blacklist = None)

   At this point it is completely built and ready
   to be fired; it is "prepared".

   However pay attention at the formatting used in
   this function because it is programmed to be pretty
   printed and may differ from the actual request.

   :param req:
   :param expose_auth: (Default value = False)

   Returns:



.. py:function:: get_recursively(search_dict, field)

   Takes a dict with nested lists and dicts,
   and searches all dicts for a key of the field
   provided.

   Originally taken from https://stackoverflow.com/a/20254842

   :param search_dict: Dict:
   :param field: str:

   Returns:

   >>> get_recursively({'id' : 5,'children' : {'id' : 6,'children' : {'id' : 7,'children' : {}}}}, 'id')
   [5, 6, 7]


.. py:function:: transform_(r, rule_keys)

   Generic Item-wise transformation function;
   The values in `r` are updated based on key-matching in `rule_keys`,
   i.e. -> out[k] = rule_keys[k] (r[k])

   HOWEVER, this can do more that straight callable mapping; can *also* update
   the key, i.e., for a given rule such that `R = rule_keys[k]`:

   R can be used to select that field to be selected in the output
   >>> r = {'a':'1','b':'2','c':'3'}
   >>> transform_(r, {'a':None})
   {'a': '1'}

   Rename a key
   >>> transform_(r, {'a':('A',None)})
   {'A': '1'}

   Apply a function to a key's value
   >>> transform_(r, {'a':('a',int)})
   {'a': 1}

   Or a combination of these
   >>> transform_(r, {'a':('A',int), 'b':None})
   {'A': 1, 'b': '2'}



.. py:function:: diff(new, old, excluded_fields = None)

   Perform a one-depth diff of a pair of dictionaries

   #TODO diff needs tests


.. py:function:: aggregate(base, group_key, item_key, condition = None)

   Abstracted groupby-sum for lists of dicts
   operationally equivalent to
   # TODO aggregate needs tests
   ```
   df = pd.DataFrame(base)
   df.where(condition).groupby(group_key)[item_key].sum()
   ```

   :param base:
   :param group_key:
   :param item_key:
   :param condition:

   Returns:



.. py:function:: breadth(d)

   Get the total 'width' of a tree

   > Why was this a thing? No idea



.. py:function:: depth(d)

   Get the maximum depth of a tree


.. py:function:: set_keys(d)

   Extract the set of all keys of a nested dict/tree


.. py:function:: keys_at(d, n, i = 0)

   Extract the keys of a tree at a given depth


.. py:function:: items_at(d, n, i = 0)

   Extract the elements from a tree at a given depth


.. py:function:: leaves(d)

   Iterate on the leaves of a tree


.. py:function:: leaf_paths(d, path = None)

.. py:function:: flatten_dict(d, head = '', sep = ':')

.. py:function:: uncollect_object(d)

.. py:function:: dict_concat_safe(d, keys, default = None)

   Really Lazy Func because `dict.get('key',default)` is a pain in the ass for lists


.. py:function:: build_default_mapping_dict_from_keys(keys)

   Constructs a mapping dictionary between (presumably) snakecase keys to 'human-readable' title case

   Intended for easy construction of presentable graphs/tables etc.

   >>> build_default_mapping_dict_from_keys(['a_b','b_c','c_d'])
   {'a_b': 'A B', 'b_c': 'B C', 'c_d': 'C D'}
