# coding=utf-8
"""
AWS based Asset handling

Includes S3, Kinesis, SSM, SQS, Lambda self-invocation and Redshift querying helpers
"""
import base64
import csv
import io
import json
import logging
import random
import time
from collections import Counter
from gzip import GzipFile
from typing import Any
from typing import AnyStr
from typing import Callable
from typing import Dict
from typing import Generator
from typing import Iterator
from typing import List
from typing import Optional
from typing import Sequence
from typing import SupportsInt
from typing import Union

import boto3
import botocore.config
import botocore.exceptions
import psycopg2.extras

from bolster import chunks

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

###
# Global Session Parent
###
# In theory this means a single auth/pool cycle... in theory..
session: Optional[boto3.Session] = None


def start_session(*args, restart=False, **kwargs) -> boto3.Session:
    global session
    if session is None or restart:
        session = boto3.Session(*args, **kwargs)
    else:
        if args or kwargs:
            raise RuntimeWarning(
                """Calling start session with arguments outside of a restart context;
                                    this might not do what you think it does."""
            )
    return session


###
# S3 Helpers
###
# https://stackoverflow.com/a/44478894
# Path Style Addressing for resolution within VPC (needs VPC-endpoint)


def get_s3_client():
    start_session()
    s3 = session.client(
        "s3",
        session.region_name,
        config=botocore.config.Config(
            s3={"addressing_style": "path"},
            connect_timeout=5,
            retries={"max_attempts": 2},
            max_pool_connections=100,
        ),
    )
    return s3


def put_s3(
    obj: Union[Sequence[Dict], io.StringIO],
    key: str,
    bucket: str,
    keys=None,
    gzip: bool = True,
    client=None,
) -> dict:
    """Take either a list of dicts (and dump them as csv to s3) or a
    StringIO buffer (and dump-as-is to s3)

    Args:
      obj: List of records to be written to CSV (or StringIO for direct upload):
      key: Destination Key
      bucket:  Destination Bucket (Default value = S3_ANALYSIS_STORE)
      keys: List of expected keys, can be used to filter or set the order of key entry in the resultant file
       (Default value = None)
      gzip: Compress the object (Default value = True)

    Returns:

    """
    if client is None:
        client = get_s3_client()

    if isinstance(obj, list):
        buffer = io.StringIO()
        if keys is None:  # Use keys inferred (i.e. no given ordering)
            keys = set([k for d in obj for k in d])
        w = csv.DictWriter(buffer, list(keys), extrasaction="ignore")
        w.writeheader()
        for row in obj:
            w.writerow(row)
    elif isinstance(obj, io.StringIO):
        buffer = obj
    else:
        raise (ValueError(f"Invalid type {type(obj)}"))
    buffer.seek(0)

    if key.endswith(".gz"):
        gzip = True
    if gzip:
        if not key.endswith(".gz"):
            key += ".gz"
        with io.BytesIO() as gz_body:
            with GzipFile(None, "wb", 9, gz_body) as gz:
                gz.write(buffer.read().encode("utf-8"))
            gz_body.seek(0)
            return client.upload_fileobj(Bucket=bucket, Key=key, Fileobj=gz_body)

    else:
        return client.put_object(Bucket=bucket, Key=key, Body=buffer.read())


def get_s3(
    key: str, bucket: str, gzip: bool = True, log_exception=True, client=None
) -> io.StringIO:
    """Get Object from S3, generally with gzip decompression included.

    Args:
      key: param bucket:
      gzip: return:
      key: str:
      bucket: str:  (Default value = S3_ANALYSIS_STORE)
      gzip: bool:  (Default value = True)

    Returns:

    """
    if client is None:
        client = get_s3_client()

    try:
        if gzip and not key.endswith(".gz"):
            key += ".gz"
        elif key.endswith(".gz") and not gzip:
            gzip = True
        obj = client.get_object(Bucket=bucket, Key=key)
        if gzip:
            got_text = GzipFile(None, "r", fileobj=io.BytesIO(obj["Body"].read()))
        else:
            got_text = obj["Body"]
        return io.StringIO(got_text.read().decode("utf-8"))
    except Exception as e:
        if log_exception:
            logger.exception(f"Error getting {key}")
        raise e


def check_s3(key: str, bucket: str, client=None) -> bool:
    """https://www.peterbe.com/plog/fastest-way-to-find-out-if-a-file-exists-in-s3

    Args:
      key: str:
      bucket: str:  (Default value = S3_ANALYSIS_STORE)

    Returns:
    """
    if client is None:
        client = get_s3_client()

    response = client.list_objects_v2(Bucket=bucket, Prefix=key)
    for obj in response.get("Contents", []):
        if obj["Key"] == key:
            return True
    else:
        return False


def get_matching_s3_objects(
    bucket: AnyStr, prefix="", suffix="", client=None
) -> Iterator:
    """
    Generate objects in an S3 bucket.

    https://alexwlchan.net/2018/01/listing-s3-keys-redux/

    :param bucket: Name of the S3 bucket.
    :param prefix: Only fetch objects whose key starts with
        this prefix (optional).
    :param suffix: Only fetch objects whose keys end with
        this suffix (optional).
    """
    if client is None:
        client = get_s3_client()

    kwargs = {"Bucket": bucket}

    # If the prefix is a single string (not a tuple of strings), we can
    # do the filtering directly in the S3 API.
    if isinstance(prefix, str):
        kwargs["Prefix"] = prefix

    while True:

        # The S3 API response is a large blob of metadata.
        # 'Contents' contains information about the listed objects.
        resp = client.list_objects_v2(**kwargs)

        try:
            contents = resp["Contents"]
        except KeyError:
            return

        for obj in contents:
            key = obj["Key"]
            if key.startswith(prefix) and key.endswith(suffix):
                yield obj

        # The S3 API is paginated, returning up to 1000 keys at a time.
        # Pass the continuation token into the next response, until we
        # reach the final page (when this field is missing).
        try:
            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
        except KeyError:
            break


def get_matching_s3_keys(bucket: AnyStr, **kwargs) -> Iterator:
    """
    Generate the keys in an S3 bucket.
    https://alexwlchan.net/2018/01/listing-s3-keys-redux/

    :param bucket: Name of the S3 bucket.
    :param prefix: Only fetch keys that start with this prefix (optional).
    :param suffix: Only fetch keys that end with this suffix (optional).
    """
    for obj in get_matching_s3_objects(bucket, **kwargs):
        yield obj["Key"]


def select_from_csv(bucket, key, fields, client=None) -> List:
    if client is None:
        client = get_s3_client()

    # noinspection SqlInjection
    r = client.select_object_content(
        Bucket=bucket,
        Key=key,
        ExpressionType="SQL",
        RequestProgress={"Enabled": True},
        Expression=f"select {','.join(fields)} from s3object s",
        InputSerialization={"CSV": {"FileHeaderInfo": "Use"}},
        OutputSerialization={"JSON": {}},
    )
    results = []
    for event in r["Payload"]:
        if "Records" in event:
            results.append(event["Records"]["Payload"].decode("utf-8"))
        elif "Progress" in event:
            continue
        elif "Stats" in event:
            stats_details = event["Stats"]["Details"]
            logger.info(stats_details)

    results = "".join(results)[:-1].replace("\n", ",")
    return json.loads("[" + results + "]")


def get_latest_key(
    prefix: str, bucket: str, key: Optional[Callable] = None, client=None
) -> str:
    """Walk a given S3 bucket for the lexicographically highest item in the given bucket (defaults to the analysis store
    defined in utils.env)

    Accepts a `key` callable that can be used to decide how the candidate keys are sorted.

    For example, to use loose-versioning, distutils.version.LooseVersion can be passed as the `key` argument

    Args:
      prefix: param bucket:
      key: return:
      prefix: str:
      bucket: str:  (Default value = S3_ANALYSIS_STORE)
      key: Optional[Callable]:  (Default value = None)

    Returns:

    """
    if client is None:
        client = get_s3_client()

    versions = sorted(
        [
            v["Key"]
            for v in client.list_objects_v2(Bucket=bucket, Prefix=prefix)["Contents"]
        ],
        key=key,
        reverse=True,
    )
    latest = versions[0]
    return latest


###
# Queueing / Notification (SQD/SNS) Helpers
###
def get_sqs_client():
    start_session()
    sqs = session.client(
        "sqs",
        endpoint_url=f"https://sqs.{session.region_name}.amazonaws.com",
        config=botocore.config.Config(
            connect_timeout=2, read_timeout=5, retries={"max_attempts": 2}
        ),
    )
    return sqs


def send_to_sqs(records: Iterator, queue: str, chunksize: int = 1, client=None) -> None:
    """Send `records` in chunks of `chunksize` for a given sqs queue in json-serialised format

    Args:
      records: param queue:
      chunksize: return:
      records: Iterator:
      queue: str:
      chunksize: int:  (Default value = 1)

    Returns:

    """
    if client is None:
        client = get_sqs_client()

    n, m = 0, 0
    sqs_incidents_url = client.get_queue_url(QueueName=queue)["QueueUrl"]
    for entry in chunks(records, chunksize):
        client.send_message(QueueUrl=sqs_incidents_url, MessageBody=json.dumps(entry))
        n += len(entry)
        m += 1
    logger.info(f"Delivered {n} items to {queue} in {m} batches")


###
# Shared Secret Manager Helpers
###
_ssm_params = {}


def get_ssm_client():
    start_session()
    ssm_client = session.client(
        "ssm",
        config=botocore.config.Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"max_attempts": 0},
            max_pool_connections=100,
        ),
    )
    return ssm_client


def get_ssm_param(param_name: str, client=None) -> str:
    """Locally memoized getter for configuration parameters stored in the AWS "Simple Systems Manager" (now just
    systems manager) Parameter Store

    Args:
      param_name: return:
      param_name: str:

    Returns:

    """
    global _ssm_params
    client = get_ssm_client()
    if param_name not in _ssm_params:
        param = client.get_parameter(Name=param_name, WithDecryption=True)

        _ssm_params[param_name] = param["Parameter"]["Value"]

    value = _ssm_params[param_name]

    return value


###
# Kinesis/Firehose Helpers
###
def fh_json_decode(content: AnyStr) -> Iterator[Union[Dict, List]]:
    """Customised JSON Decoder for consuming Firehose batched records;

    Firehose doesn't include entry separators between entries, so we intercept the raw_decoder
    on JSONDecodeError and 'skip' over the 'where is my comma?' issue and continue to parse the
    rest of the content until we reach the end of the given content string.

    Args:
      content: AnyStr:

    Returns:

    >>> list(fh_json_decode('{"test":"value"}{"test":"othervalue"}'))
    [{'test': 'value'}, {'test': 'othervalue'}]
    """
    decoder = json.JSONDecoder()
    content_length = len(content)
    decode_index = 0

    while decode_index < content_length:
        try:
            obj, decode_index = decoder.raw_decode(content, decode_index)
            yield obj
        except json.JSONDecodeError:
            # Scan forward and keep trying to decode
            decode_index += 1


def decapsulate_kinesis_payloads(event: Dict) -> List[Dict]:
    """Decapsulate base64 encoded kinesis data records to a list

    Args:
      event: Dict:

    Returns:

    """
    records = []
    for record in event["Records"]:
        try:
            b64payload = base64.b64decode(record["kinesis"]["data"]).decode("utf-8")
            records.append(json.loads(b64payload))
        except Exception:
            logger.exception(f"FAILED {record}")
    return records


def iterate_kinesis_payloads(event: Dict) -> Generator[Dict, None, None]:
    """Iterate over a base64 encoded kinesis data record, yielding entries

    Args:
      event: return:
      event: Dict:

    Returns:

    """
    for record in event["Records"]:
        try:
            b64payload = base64.b64decode(record["kinesis"]["data"]).decode("utf-8")
            yield json.loads(b64payload)
        except Exception:
            logger.exception(f"FAILED {record}")


class KinesisLoader(object):
    """Kinesis batchwise insertion handler with chunking and retry"""

    def __init__(
        self, batch_size: int = 500, maximum_records: int = None, stream: str = None
    ):
        """
        The default batch_size here is to match the maximum allowed by Kinesis in a PutRecords request
        """
        start_session()
        self.batch_size = min(batch_size, 500)
        self.maximum_records = maximum_records
        self.kinesis_client = session.client(
            "kinesis",
            config=botocore.config.Config(
                connect_timeout=5,
                max_pool_connections=100,
                read_timeout=5,
                retries={"max_attempts": 3},
            ),
        )
        if stream.startswith("arn"):
            stream = stream.split("/")[-1]
        self.stream = stream

    def generate_and_submit(
        self, items: Iterator, partition_key: str = None
    ) -> SupportsInt:
        """Submit batches of items to the configured stream

        Args:
          items: param partition_key:
          items: Iterator:
          partition_key: str:  (Default value = None)

        Returns:

        """
        counter = 0
        # Simple cutoff here - guaranteed to not send in more than maximum_records, with single batch granularity
        for i, batched_items in enumerate(chunks(items, self.batch_size)):
            records_batch = [
                {
                    "Data": json.dumps(item).encode("utf-8"),
                    "PartitionKey": str(random.random())
                    if partition_key is None
                    else partition_key,
                }
                for item in batched_items
            ]
            request = {"Records": records_batch, "StreamName": self.stream}

            response = self.kinesis_client.put_records(**request)
            self.submit_batch_until_successful(records_batch, response)

            counter += len(records_batch)
            if counter > 1:
                logger.info("Batch inserted. Total records: {}".format(str(counter)))

        return counter

    def submit_batch_until_successful(self, this_batch: List, response: Dict):
        """If needed, retry a batch of records, backing off exponentially until it goes through

        Args:
          this_batch: List:
          response: Dict:

        Returns:

        """
        retry_interval = 0.25

        failed_record_count = response["FailedRecordCount"]
        while failed_record_count:
            time.sleep(retry_interval)

            # Failed records don't contain the original contents - we have to correlate with the input by position
            failed_records = [
                this_batch[i]
                for i, record in enumerate(response["Records"])
                if "ErrorCode" in record
            ]

            logger.info(
                "Incrementing exponential back off and retrying {} failed records".format(
                    str(len(failed_records))
                )
            )
            retry_interval = min(retry_interval * 2, 4)
            request = {"Records": failed_records, "StreamName": self.stream}
            result = self.kinesis_client.put_records(**request)
            failed_record_count = result["FailedRecordCount"]


def send_to_kinesis(
    records: Iterator[Sequence], stream: str, partition_key: str = None
) -> int:
    """Accessory function for the KinesisLoader class

    Args:
      records: Iterator[Sequence]:
      stream: str:
      partition_key: str:  (Default value = None)

    Returns:

    """
    loader = KinesisLoader(stream=stream)
    return loader.generate_and_submit(
        (record for record in records), partition_key=partition_key
    )


def get_sns_client():
    start_session()
    sns = session.client(
        "sns",
        session.region_name,
        config=botocore.config.Config(
            connect_timeout=5, retries={"max_attempts": 2}, max_pool_connections=100
        ),
    )
    return sns


def invoke_self_async(event: Dict, context: Any):
    """Have the Lambda invoke itself asynchronously, passing the same event it received originally,
    and tagging the event as 'async' so it's actually processed

    THIS DOES NOT WORK FROM WITHIN A VPC! (There is no lambda-invoke endpoint accessible without poking
    lots of holes in the VPC.

    Args:
      event: Dict:
      context: Any:

    Returns:

    """
    start_session()
    event["async"] = True
    session.client("lambda").invoke(
        FunctionName=context.invoked_function_arn,
        InvocationType="Event",
        Payload=bytes(json.dumps(event).encode("utf-8")),
    )


def query(
    q: str, redshift_conn_dict: dict, named_cursor="bolster_query_cursor", **kwargs
) -> Iterator[Dict]:
    """Helper for making queries to redshift (or any postgres compatible backend)

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

    Args:
      q: param redshift_conn_dict:
      kwargs: return:
      q: str:
      redshift_conn_dict: dict:  (Default value = None)
      **kwargs:

    Returns:

    """
    try:
        with psycopg2.connect(**redshift_conn_dict) as conn:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor, name=named_cursor
            ) as cur:
                cur.execute(q, vars=kwargs if kwargs is not None else {})
                yield from cur
    except BaseException:  # todo workout what the likely exceptions being thrown by postgreql are likely to be
        logger.exception(f"Failed with connection: {redshift_conn_dict}")
        raise


def SQSWrapper(  # noqa: C901
    event,
    context,
    queuename,
    function,
    timeout=60000,
    reinvokelimit=10,
    maxmessages=1,
    raise_exceptions=True,
    deduplicate=False,
    fkwargs={},
    client=None,
):
    if client is None:
        client = get_sqs_client()
    try:
        md5_map = Counter()
        meta_counter = Counter()
        try:
            sqs_url = client.get_queue_url(QueueName=queuename)["QueueUrl"]
        except BaseException:
            logger.exception(f"Error connecting to {queuename}")
            raise
        n = 0
        while context.get_remaining_time_in_millis() > timeout:
            sqs_item = client.receive_message(
                QueueUrl=sqs_url, MaxNumberOfMessages=maxmessages, WaitTimeSeconds=3
            )
            if not len(sqs_item.get("Messages", [])):
                if n == 0:
                    logger.debug(f"No messages in {sqs_item}")
                return  # EXIT PATH

            for message in sqs_item["Messages"]:
                receipt_handle = message["ReceiptHandle"]

                if not deduplicate or message["MD5OfBody"] not in md5_map:
                    try:
                        results = function(message["Body"], **fkwargs)
                    except BaseException:
                        results = None
                        logger.exception(f"{function.__name__}: Failed on {message}")
                        if raise_exceptions:
                            raise

                    if isinstance(results, dict):
                        logger.info(f"Got {results}")
                        meta_counter.update(results)
                    elif results is None:
                        pass  # Assume 'None' means function 'failed'
                    else:
                        logger.info(
                            f"Not sure what to do with type {type(results)}:{results}, ignoring"
                        )
                else:
                    logger.info(
                        f"Skipping duplicate message: {message['Body']} seen {md5_map[message['MD5OfBody']]} "
                        f"times already"
                    )

                md5_map[message["MD5OfBody"]] += 1

                # Delete received message from queue
                client.delete_message(QueueUrl=sqs_url, ReceiptHandle=receipt_handle)
                n += 1
        logger.info(f"Processed {n} items before wrapping up")
        approx = (
            client.get_queue_attributes(
                QueueUrl=sqs_url, AttributeNames=["ApproximateNumberOfMessages"]
            )
            .get("Attributes", {})
            .get("ApproximateNumberOfMessages", -1)
        )
        approx = int(approx)
        if approx > reinvokelimit:
            logger.info(
                f"There are {approx} messages left on the queue; reinvoking asynchronously"
            )
            invoke_self_async(event, context)

        return meta_counter

    except BaseException:
        logger.exception(f"Unhandled Exception in {context.function_name}")
        raise
