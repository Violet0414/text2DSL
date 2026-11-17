"""执行层测试:wren CLI JSONL 解析(实测事实 #4)、超时/失败分类、角色映射。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from chatbi.executor import WrenCliExecutor, derive_roles


@dataclass
class FakeCompleted:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeSubprocess:
    """subprocess.run 替身:按注入结果返回并记录调用参数。"""

    def __init__(self, result=None, raises=None):
        self.result = result or FakeCompleted()
        self.raises = raises
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.raises is not None:
            raise self.raises
        return self.result


def _executor(fake_sp) -> WrenCliExecutor:
    return WrenCliExecutor(runner=fake_sp, wren_bin="/usr/bin/true")


SQL = "SELECT channel, SUM(sales_amount) FROM t GROUP BY channel"


class TestJsonlParsing:
    def test_parses_jsonl_rows_not_array(self):
        # 实测事实 #4:wren -o json 输出 JSONL(逐行 JSON 对象,非数组)
        lines = (
            json.dumps({"channel": "华东", "sales_amount": 100})
            + "\n"
            + json.dumps({"channel": "华南", "sales_amount": 200})
            + "\n"
        )
        result = _executor(FakeSubprocess(FakeCompleted(stdout=lines))).execute(SQL)
        assert result.is_ok
        assert result.row_count == 2
        assert result.rows[0]["channel"] == "华东"
        assert result.rows[1]["sales_amount"] == 200

    def test_columns_preserve_first_row_order(self):
        lines = json.dumps({"sales_amount": 1, "channel": "华东"}) + "\n"
        result = _executor(FakeSubprocess(FakeCompleted(stdout=lines))).execute(SQL)
        assert result.columns == ("sales_amount", "channel")

    def test_empty_output_is_zero_rows_success(self):
        result = _executor(FakeSubprocess(FakeCompleted(stdout=""))).execute(SQL)
        assert result.is_ok
        assert result.row_count == 0
        assert result.rows == ()
        assert result.error_class is None


class TestFailureClassification:
    def test_timeout_classified_as_timeout(self):
        fake = FakeSubprocess(raises=subprocess.TimeoutExpired(cmd="wren", timeout=6))
        result = _executor(fake).execute(SQL)
        assert not result.is_ok
        assert result.error_class == "timeout"
        assert result.rows == ()

    def test_nonzero_exit_classified_as_cli_error(self):
        fake = FakeSubprocess(
            FakeCompleted(returncode=1, stderr="Unknown measure: ghost")
        )
        result = _executor(fake).execute(SQL)
        assert not result.is_ok
        assert result.error_class == "cli_error"
        assert "Unknown measure" in (result.error_message or "")

    def test_invalid_jsonl_line_is_cli_error_not_crash(self):
        lines = "not-a-json-line\n"
        result = _executor(FakeSubprocess(FakeCompleted(stdout=lines))).execute(SQL)
        assert not result.is_ok
        assert result.error_class == "parse_error"


class TestCliInvocation:
    def test_command_includes_limit_and_json_output(self):
        fake = FakeSubprocess(FakeCompleted(stdout=""))
        _executor(fake).execute(SQL, limit=500)
        argv = fake.calls[0]["args"][0]
        assert "--limit" in argv and "500" in argv
        assert "-o" in argv and "json" in argv
        assert SQL in argv

    def test_default_limit_is_enforced(self):
        fake = FakeSubprocess(FakeCompleted(stdout=""))
        _executor(fake).execute(SQL)
        argv = fake.calls[0]["args"][0]
        assert str(fake.calls[0]["kwargs"].get("timeout", 0)) == str(
            WrenCliExecutor.EXECUTION_TIMEOUT_S
        )
        idx = argv.index("--limit")
        assert int(argv[idx + 1]) > 0


class TestDeriveRoles:
    def test_roles_from_cube_query_members(self):
        cube_query = {
            "cube": "sales",
            "measures": ["sales_amount"],
            "dimensions": ["channel"],
            "timeDimensions": [
                {"dimension": "order_date", "dateRange": ["2026-10-01", "2026-11-01"]}
            ],
        }
        roles = derive_roles(cube_query)
        assert roles == {
            "sales_amount": "measure",
            "channel": "dimension",
            "order_date": "time",
        }

    def test_executor_carries_roles(self):
        lines = json.dumps({"channel": "华东", "sales_amount": 100}) + "\n"
        cube_query = {
            "cube": "sales",
            "measures": ["sales_amount"],
            "dimensions": ["channel"],
        }
        result = _executor(FakeSubprocess(FakeCompleted(stdout=lines))).execute(
            SQL, cube_query=cube_query
        )
        assert result.roles == {"sales_amount": "measure", "channel": "dimension"}
