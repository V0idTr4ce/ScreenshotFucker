# 实验 JSON 写法

文件必须是 UTF-8，`schema_version` 为 `1`。

```json
{
  "schema_version": 1,
  "name": "我的实验",
  "description": "可选",
  "vars": {
    "port": "26000",
    "role": "yzx"
  },
  "settings": {
    "window_cols": 120,
    "window_rows": 52,
    "window_width": 1280,
    "window_height": 980,
    "buffer_rows": 800,
    "speed": 1.5,
    "clear_between": true,
    "capture_from_top": true
  },
  "session": {
    "open": [
      {"text": "gsql -d postgres -p ${port} -r", "wait": "gsql"}
    ],
    "prepare_at": [
      {
        "if": {"min": 2, "max": 20},
        "cmds": [{"text": "\\c DB_em", "wait": "gsql"}]
      }
    ],
    "from": {
      "connect_only_below": 21,
      "replay_from": 21
    }
  },
  "boxes": [
    {
      "n": 1,
      "title": "第一框",
      "script": [
        "SELECT 1;"
      ]
    }
  ]
}
```

## `${变量}`

`session` 和 `boxes` 里的字符串都可以写 `${name}`。取值来自本文件的 `vars`，再被 `config.json` 里的 `vars` 覆盖。

## 灰框

每一框对应一张截图。

- `n`：从 1 连续编号
- `title`：`--list` 时显示
- `script`：字符串数组（或一整段字符串）。每一行单独回车，gsql 的续行提示会和手工输入一样
- `cmds`：某一行需要 `wait` / `timeout` / `skip_if` / `kind` 时用这个，不要和 `script` 混用
- `timeout`：这一框每行的默认等待秒数

命令对象：

| 字段 | 含义 |
| --- | --- |
| `text` | 要敲进去的一行 |
| `wait` | `shell`、`gsql`、`gsql_more`（可省略，程序会猜） |
| `timeout` | 秒 |
| `kind` | `shell` 表示不要当成 SQL |
| `skip_if` | `already_omm`：当前用户已经是 omm 时跳过 `su - omm` |

等待规则：`gsql ...`、以 `\` 开头、或以 `;` 结尾的行，等到 gsql 就绪提示符。gsql 里尚未结束的行等到续行提示符（如 `db_em-#`）。

## `--at` / `--from`

- `--at N`：先执行 `session.open` 和匹配的 `prepare_at`，再从第 N 框开始。前面框里的 SQL 不跑。
- `--from N`：若 `N < from.connect_only_below`，效果和 `--at` 一样；否则先静默回放 `from.replay_from` 到 `N-1`，再从 N 开始。

## 例子

`example-echo.json` 只有 `hostname` / `echo` 两框，用来确认截图，不连数据库。
