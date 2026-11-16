"""Arrow cells that are not JSON-native must not break the Data tab.

A timestamp column used to surface as a Python datetime, which json.dumps rejects — and because
_send_json raises after send_response, the browser saw a dropped connection, not a 500. The same
path broke date/time/duration/decimal/binary columns. These tests pin the conversion for every one
of them, over the handler and over HTTP, plus the timestamp display flag and the Arrow-file viewer.
"""
import datetime
import decimal
import json
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from lance_viewer import handlers, util
from lance_viewer.server import Handler


def _lance():
    return pytest.importorskip("lance")


def _pa():
    return pytest.importorskip("pyarrow")


@pytest.fixture
def typed_dataset(tmp_path):
    """One row per non-JSON-native Arrow type, plus a vector and a plain int."""
    lance, pa = _lance(), _pa()
    path = tmp_path / "typed.lance"
    now = datetime.datetime(2026, 11, 16, 10, 30, 0)
    lance.write_dataset(pa.table({
        "id": pa.array([0, 1], type=pa.int64()),
        "created_at": pa.array([now, now + datetime.timedelta(minutes=1)], type=pa.timestamp("us")),
        "updated_tz": pa.array([now.replace(tzinfo=datetime.timezone.utc)] * 2,
                               type=pa.timestamp("ms", tz="UTC")),
        "birth_date": pa.array([datetime.date(2020, 1, 1)] * 2, type=pa.date32()),
        "clock": pa.array([datetime.time(10, 30)] * 2, type=pa.time64("us")),
        "span": pa.array([datetime.timedelta(days=1)] * 2, type=pa.duration("us")),
        "amount": pa.array([decimal.Decimal("1.25")] * 2, type=pa.decimal128(10, 2)),
        "blob": pa.array([b"hi"] * 2, type=pa.binary()),
        "vec": pa.array([[1.0, 2.0]] * 2, type=pa.list_(pa.float32(), 2)),
    }), str(path))
    return path


# ---------- the conversion helper ----------

def test_json_safe_value_converts_every_non_native_type():
    now = datetime.datetime(2026, 11, 16, 10, 30, 0)
    assert util.json_safe_value(now) == int(now.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
    assert util.json_safe_value(datetime.date(2020, 1, 1)) == "2020-01-01"
    assert util.json_safe_value(datetime.time(10, 30)) == "10:30:00"
    assert util.json_safe_value(datetime.timedelta(days=1)) == "1 day, 0:00:00"
    assert util.json_safe_value(decimal.Decimal("1.25")) == 1.25
    assert util.json_safe_value(b"hi") == "hi"
    # native values pass through untouched
    assert util.json_safe_value(5) == 5
    assert util.json_safe_value("x") == "x"
    assert util.json_safe_value(None) is None


def test_naive_timestamp_is_treated_as_utc():
    naive = datetime.datetime(2026, 1, 1, 0, 0, 0)
    aware = naive.replace(tzinfo=datetime.timezone.utc)
    assert util.json_safe_value(naive) == util.json_safe_value(aware)


# ---------- the Data tab ----------

def test_typed_dataset_is_json_serializable(typed_dataset):
    info, err = handlers.dataset_info(str(typed_dataset), limit=2)
    assert err is None, err
    json.dumps(info)   # the exact call that used to raise TypeError

    cols = info["columns"]
    assert isinstance(cols["created_at"][0], int)          # epoch ms
    assert cols["birth_date"][0] == "2020-01-01"
    assert cols["clock"][0] == "10:30:00"
    assert cols["amount"][0] == 1.25
    assert cols["blob"][0] == "hi"
    assert cols["vec"][0] == [1.0, 2.0]


def test_timestamp_columns_are_flagged_for_display(typed_dataset):
    info, err = handlers.dataset_info(str(typed_dataset), limit=2)
    assert err is None, err
    flags = {c["name"]: c["timestamp"] for c in info["display"]}
    assert flags["created_at"] is True
    assert flags["updated_tz"] is True
    assert flags["birth_date"] is False    # a date is not an instant
    assert flags["id"] is False


def test_null_first_row_timestamp_is_still_flagged(tmp_path):
    lance, pa = _lance(), _pa()
    path = tmp_path / "nullfirst.lance"
    lance.write_dataset(pa.table({
        "ts": pa.array([None, datetime.datetime(2026, 1, 1)], type=pa.timestamp("us")),
    }), str(path))

    info, err = handlers.dataset_info(str(path), limit=2)
    assert err is None, err
    flag = next(c["timestamp"] for c in info["display"] if c["name"] == "ts")
    assert flag is True                    # type-based, not dependent on the first row
    assert info["columns"]["ts"][0] is None
    json.dumps(info)


def test_list_of_timestamps_is_safe(tmp_path):
    lance, pa = _lance(), _pa()
    path = tmp_path / "listts.lance"
    lance.write_dataset(pa.table({
        "events": pa.array([[datetime.datetime(2026, 1, 1), datetime.datetime(2026, 1, 2)]],
                           type=pa.list_(pa.timestamp("us"))),
    }), str(path))

    info, err = handlers.dataset_info(str(path), limit=1)
    assert err is None, err
    json.dumps(info)
    assert all(isinstance(v, int) for v in info["columns"]["events"][0])


# ---------- the Arrow-file viewer (cell_to_py path) ----------

def test_arrow_file_with_timestamp_is_serializable(tmp_path):
    pa = _pa()
    import pyarrow.ipc as ipc
    folder = tmp_path / "arrowdir"
    folder.mkdir()
    target = folder / "del.arrow"
    table = pa.table({
        "_rowid": pa.array([1, 2], type=pa.int64()),
        "when": pa.array([datetime.datetime(2026, 1, 1)] * 2, type=pa.timestamp("us")),
    })
    with pa.OSFile(str(target), "wb") as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)

    info, err = handlers.arrow_info(str(folder), "del.arrow")
    assert err is None, err
    json.dumps(info)
    assert isinstance(info["rows"][0]["when"], int)


# ---------- over HTTP, the way production hits it ----------

def test_http_data_with_timestamp_returns_200(typed_dataset):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        q = urllib.parse.urlencode({"path": str(typed_dataset), "limit": 2})
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dataset?{q}") as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
        assert isinstance(body["columns"]["created_at"][0], int)
    finally:
        srv.shutdown()
        srv.server_close()