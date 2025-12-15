bolster.utils
=============

.. py:module:: bolster.utils

.. autoapi-nested-parse::

   Utility bits and pieces.

   Random helpful functions that don't fit anywhere else:
   - timed: decorator to time function execution
   - TqdmLoggingHandler: logging that plays nice with tqdm progress bars
   - web: resilient web scraping helpers
   - dt: datetime utilities
   - io: file/data helpers
   - aws/azure: cloud platform helpers



Submodules
----------

.. toctree::
   :maxdepth: 1

   /autoapi/bolster/utils/aws/index
   /autoapi/bolster/utils/azure/index
   /autoapi/bolster/utils/deco/index
   /autoapi/bolster/utils/dt/index
   /autoapi/bolster/utils/io/index
   /autoapi/bolster/utils/web/index


Attributes
----------

.. autoapisummary::

   bolster.utils.F
   bolster.utils.version_no


Classes
-------

.. autoapisummary::

   bolster.utils.TqdmLoggingHandler


Functions
---------

.. autoapisummary::

   bolster.utils.timed


Package Contents
----------------

.. py:data:: F

.. py:data:: version_no

.. py:class:: TqdmLoggingHandler(level=logging.NOTSET)

   Bases: :py:obj:`logging.Handler`


   Custom logging handler that uses tqdm to display log messages.
   i.e. `logging.getLogger().addHandler(TqdmLoggingHandler())`

   Initializes the instance - basically setting the formatter to None
   and the filter list to empty.


   .. py:method:: emit(record)

      Do whatever it takes to actually log the specified logging record.

      This version is intended to be implemented by subclasses and so
      raises a NotImplementedError.



.. py:function:: timed(func)

   This decorator prints the execution time for the decorated function.


