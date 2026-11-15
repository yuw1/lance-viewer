"""Storage-option normalisation tests (no network, no credentials).

`storage_option_set` is deliberately small: s3:// always gets virtual-hosted addressing, everything
else is handed through untouched. The tests pin the two consequences that are easy to regress --
that oss:// is left alone, and that a bucket already present in the endpoint is not added twice.
"""
from lance_viewer import lance_client


def test_s3_gets_the_flag_and_a_bucket_scoped_endpoint():
    out = lance_client.storage_option_set(
        "s3://example-bucket/table.lance",
        {"endpoint": "https://s3.us-east-1.amazonaws.com", "region": "us-east-1"},
    )
    assert out["aws_virtual_hosted_style_request"] == "true"
    assert out["endpoint"] == "https://example-bucket.s3.us-east-1.amazonaws.com"
    assert out["region"] == "us-east-1"


def test_region_endpoint_is_always_bucket_scoped():
    # No provider detection: any s3:// endpoint gets the bucket, including plain AWS
    out = lance_client.storage_option_set(
        "s3://example-bucket/table.lance", {"endpoint": "https://s3.us-east-1.amazonaws.com"}
    )
    assert out["endpoint"] == "https://example-bucket.s3.us-east-1.amazonaws.com"
    assert out["aws_virtual_hosted_style_request"] == "true"


def test_existing_bucket_is_not_added_twice():
    out = lance_client.storage_option_set(
        "s3://example-bucket/table.lance",
        {"endpoint": "https://example-bucket.s3.us-east-1.amazonaws.com"},
    )
    assert out["endpoint"] == "https://example-bucket.s3.us-east-1.amazonaws.com"


def test_bucket_scoped_endpoint_keeps_scheme_path_and_port():
    got = lance_client.bucket_scoped_endpoint("http://storage.example.com:9000/base", "example-bucket")
    assert got == "http://example-bucket.storage.example.com:9000/base"


def test_bucket_scoped_endpoint_passes_through_when_incomplete():
    assert lance_client.bucket_scoped_endpoint("", "example-bucket") == ""
    assert lance_client.bucket_scoped_endpoint("https://s3.us-east-1.amazonaws.com", "") == \
        "https://s3.us-east-1.amazonaws.com"


def test_oss_is_untouched():
    # opendal-service-oss already defaults to virtual addressing; adding the aws flag would be inert
    opts = {"access_key_id": "id", "access_key_secret": "secret",
            "endpoint": "https://oss-cn-beijing.aliyuncs.com"}
    out = lance_client.storage_option_set("oss://example-bucket/table.lance", opts)
    assert out == opts


def test_local_paths_are_untouched():
    opts = {"endpoint": "https://s3.us-east-1.amazonaws.com"}
    assert lance_client.storage_option_set("/tmp/table.lance", opts) == opts


def test_input_dict_is_not_mutated():
    opts = {"endpoint": "https://s3.us-east-1.amazonaws.com"}
    lance_client.storage_option_set("s3://example-bucket/table.lance", opts)
    assert opts == {"endpoint": "https://s3.us-east-1.amazonaws.com"}


def test_none_options_pass_through():
    assert lance_client.storage_option_set("s3://example-bucket/t.lance", None) is None