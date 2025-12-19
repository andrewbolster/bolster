bolster.utils.aws
=================

.. py:module:: bolster.utils.aws

.. autoapi-nested-parse::

   AWS based Asset handling

   Includes S3, Kinesis, SSM, SQS, Lambda self-invocation and Redshift querying helpers



Attributes
----------

.. autoapisummary::

   bolster.utils.aws.logger
   bolster.utils.aws.session


Classes
-------

.. autoapisummary::

   bolster.utils.aws.KinesisLoader


Functions
---------

.. autoapisummary::

   bolster.utils.aws.chunks
   bolster.utils.aws.start_session
   bolster.utils.aws.get_s3_client
   bolster.utils.aws.put_s3
   bolster.utils.aws.get_s3
   bolster.utils.aws.check_s3
   bolster.utils.aws.get_matching_s3_objects
   bolster.utils.aws.get_matching_s3_keys
   bolster.utils.aws.select_from_csv
   bolster.utils.aws.get_latest_key
   bolster.utils.aws.get_sqs_client
   bolster.utils.aws.send_to_sqs
   bolster.utils.aws.get_ssm_client
   bolster.utils.aws.get_ssm_param
   bolster.utils.aws.fh_json_decode
   bolster.utils.aws.decapsulate_kinesis_payloads
   bolster.utils.aws.iterate_kinesis_payloads
   bolster.utils.aws.send_to_kinesis
   bolster.utils.aws.get_sns_client
   bolster.utils.aws.invoke_self_async
   bolster.utils.aws.query
   bolster.utils.aws.SQSWrapper


Package Contents
----------------

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


.. py:data:: logger

.. py:data:: session
   :type:  Optional[boto3.Session]
   :value: None


.. py:function:: start_session(*args, restart=False, **kwargs)

.. py:function:: get_s3_client()

.. py:function:: put_s3(obj, key, bucket, keys=None, gzip = True, client=None)

   Take either a list of dicts (and dump them as csv to s3) or a
   StringIO buffer (and dump-as-is to s3)

   :param obj: List of records to be written to CSV (or StringIO for direct upload):
   :param key: Destination Key
   :param bucket: Destination Bucket (Default value = S3_ANALYSIS_STORE)
   :param keys: List of expected keys, can be used to filter or set the order of key entry in the resultant file
                (Default value = None)
   :param gzip: Compress the object (Default value = True)

   Returns:



.. py:function:: get_s3(key, bucket, gzip = True, log_exception=True, client=None)

   Get Object from S3, generally with gzip decompression included.

   :param key: param bucket:
   :param gzip: return:
   :param key: str:
   :param bucket: str:  (Default value = S3_ANALYSIS_STORE)
   :param gzip: bool:  (Default value = True)

   Returns:



.. py:function:: check_s3(key, bucket, client=None)

   https://www.peterbe.com/plog/fastest-way-to-find-out-if-a-file-exists-in-s3

   :param key: str:
   :param bucket: str:  (Default value = S3_ANALYSIS_STORE)

   Returns:


.. py:function:: get_matching_s3_objects(bucket, prefix='', suffix='', client=None)

   Generate objects in an S3 bucket.

   https://alexwlchan.net/2018/01/listing-s3-keys-redux/

   :param bucket: Name of the S3 bucket.
   :param prefix: Only fetch objects whose key starts with
       this prefix (optional).
   :param suffix: Only fetch objects whose keys end with
       this suffix (optional).


.. py:function:: get_matching_s3_keys(bucket, **kwargs)

   Generate the keys in an S3 bucket.
   https://alexwlchan.net/2018/01/listing-s3-keys-redux/

   :param bucket: Name of the S3 bucket.
   :param prefix: Only fetch keys that start with this prefix (optional).
   :param suffix: Only fetch keys that end with this suffix (optional).


.. py:function:: select_from_csv(bucket, key, fields, client=None)

.. py:function:: get_latest_key(prefix, bucket, key = None, client=None)

   Walk a given S3 bucket for the lexicographically highest item in the given bucket (defaults to the analysis store
   defined in utils.env)

   Accepts a `key` callable that can be used to decide how the candidate keys are sorted.

   For example, to use loose-versioning, distutils.version.LooseVersion can be passed as the `key` argument

   :param prefix: param bucket:
   :param key: return:
   :param prefix: str:
   :param bucket: str:  (Default value = S3_ANALYSIS_STORE)
   :param key: Optional[Callable]:  (Default value = None)

   Returns:



.. py:function:: get_sqs_client()

.. py:function:: send_to_sqs(records, queue, chunksize = 1, client=None)

   Send `records` in chunks of `chunksize` for a given sqs queue in json-serialised format

   :param records: param queue:
   :param chunksize: return:
   :param records: Iterator:
   :param queue: str:
   :param chunksize: int:  (Default value = 1)

   Returns:



.. py:function:: get_ssm_client()

.. py:function:: get_ssm_param(param_name, client=None)

   Locally memoized getter for configuration parameters stored in the AWS "Simple Systems Manager" (now just
   systems manager) Parameter Store

   :param param_name: return:
   :param param_name: str:

   Returns:



.. py:function:: fh_json_decode(content)

   Customised JSON Decoder for consuming Firehose batched records;

   Firehose doesn't include entry separators between entries, so we intercept the raw_decoder
   on JSONDecodeError and 'skip' over the 'where is my comma?' issue and continue to parse the
   rest of the content until we reach the end of the given content string.

   :param content: AnyStr:

   Returns:

   >>> list(fh_json_decode('{"test":"value"}{"test":"othervalue"}'))
   [{'test': 'value'}, {'test': 'othervalue'}]


.. py:function:: decapsulate_kinesis_payloads(event)

   Decapsulate base64 encoded kinesis data records to a list

   :param event: Dict:

   Returns:



.. py:function:: iterate_kinesis_payloads(event)

   Iterate over a base64 encoded kinesis data record, yielding entries

   :param event: return:
   :param event: Dict:

   Returns:



.. py:class:: KinesisLoader(batch_size = 500, maximum_records = None, stream = None)

   Bases: :py:obj:`object`


   Kinesis batchwise insertion handler with chunking and retry

   The default batch_size here is to match the maximum allowed by Kinesis in a PutRecords request


   .. py:attribute:: batch_size


   .. py:attribute:: maximum_records
      :value: None



   .. py:attribute:: kinesis_client


   .. py:attribute:: stream
      :value: None



   .. py:method:: generate_and_submit(items, partition_key = None)

      Submit batches of items to the configured stream

      :param items: param partition_key:
      :param items: Iterator:
      :param partition_key: str:  (Default value = None)

      Returns:




   .. py:method:: submit_batch_until_successful(this_batch, response)

      If needed, retry a batch of records, backing off exponentially until it goes through

      :param this_batch: List:
      :param response: Dict:

      Returns:




.. py:function:: send_to_kinesis(records, stream, partition_key = None)

   Accessory function for the KinesisLoader class

   :param records: Iterator[Sequence]:
   :param stream: str:
   :param partition_key: str:  (Default value = None)

   Returns:



.. py:function:: get_sns_client()

.. py:function:: invoke_self_async(event, context)

   Have the Lambda invoke itself asynchronously, passing the same event it received originally,
   and tagging the event as 'async' so it's actually processed

   THIS DOES NOT WORK FROM WITHIN A VPC! (There is no lambda-invoke endpoint accessible without poking
   lots of holes in the VPC.

   :param event: Dict:
   :param context: Any:

   Returns:



.. py:function:: query(q, redshift_conn_dict, named_cursor='bolster_query_cursor', **kwargs)

   Helper for making queries to redshift (or any postgres compatible backend)

   .. code-block:: json

       {
         "user":"USERNAME",
         "host":"HOSTNAME",
         "connect_timeout":3,
         "dbname":"DATABASE",
         "port":5439,
         "password":"SUPERSECRETPASSWORD1111"
       }


   This function implements the 'is_local' check if it is getting it's configuration
   dictionary from the parameter store, and will overwrite the 'host' in the store
   with a resolvable hostname for the ALDS datastore.

   Basically, if you're not working on ALDS, in a few very specific locations, or
   are outside the ALDS VPC, give this a sensible dictionary.

   kwargs are passed through as `vars` to the SQL execution, i.e. to be used with
   substitution queries, eg:

   .. code-block:: python

       query("select * from table where id = %(my_id)s", my_id = 14228)


   NOTE! If you use % wildcards (i.e. LIKE '%string'), you're gonna have a bad time... (Use the POSIX regex instead:
   https://docs.aws.amazon.com/redshift/latest/dg/pattern-matching-conditions-posix.html)

   :param q: param redshift_conn_dict:
   :param kwargs: return:
   :param q: str:
   :param redshift_conn_dict: dict:  (Default value = None)
   :param \*\*kwargs:

   Returns:



.. py:function:: SQSWrapper(event, context, queuename, function, timeout=60000, reinvokelimit=10, maxmessages=1, raise_exceptions=True, deduplicate=False, fkwargs={}, client=None)
