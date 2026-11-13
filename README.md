# ScreenshotFucker

在真实终端里按实验报告的「灰框」自动敲命令，并在本机窗口里逐框截图。

要执行的代码单独放在 `labs/*.json` 里，改实验不用改程序。窗口标题默认是 `用户@主机`。一框输出太长时只截**开头**（命令和前几行），下面被挡住的不管。

入口只有 `ScreenshotFucker.py`。Windows 上直接：

```bat
python ScreenshotFucker.py
```

第一次会从 `config.example.json` 生成 `config.json`，并询问实验机地址、SSH 用户、SSH 密码，写进配置后立刻开跑。之后再运行同一条命令即可。密码也可以只放环境变量 `SFF_SSH_PASS`。

截图保存在 `shots/01.png`、`02.png` …

## 依赖

- 本机 Python 3.8+
- 本机 Pillow：`python -m pip install -r requirements.txt`
- 本机 OpenSSH 客户端（`ssh`、`scp`）。Windows 可选功能「OpenSSH 客户端」，或 Git for Windows
- 实验机：Linux、Python 3，以及 JSON 里要跑的程序（如 `gsql`）

## 目录结构

```
release/
  ScreenshotFucker.py          唯一入口。python ScreenshotFucker.py 即可启动
  screenshotfucker/            引擎包（一般不用单独运行）
    __init__.py                包版本号
    labfile.py                 读取/校验实验 JSON，替换 ${变量}
    local.py                   本机编排：上传、SSH、等粉红条、截窗、回 ACK
    capture.py                 找终端窗口、截图、按粉红条裁切
    consolewin.py              窗口标题、高度、关 QuickEdit、清缓冲、钉在开头
    sshutil.py                 OpenSSH 路径、ASKPASS、scp 去掉 CR
    protocol.py                粉红条颜色、SFF_SHOT / SFF_ACK 握手标记
    remote_runner.py           上传到 Linux 的脚本：真实 PTY 里打字、画边界条
  labs/
    opengauss-e5.json          实验 5 的 34 个灰框（索引/视图/序列）
    example-echo.json          两框 echo，用来确认截图流水线
    FORMAT.md                  怎么自己写一份实验 JSON
  tests/
    run_tests.py               本地测试入口：python tests/run_tests.py
    README.md                  测试说明
    labs/
      boundaries.json          中文/失败/超长/超宽/ANSI/假 Password
      at-from.json             --at 与 --from 对照
      bad-dup.json             编号重复（应校验失败）
      bad-gap.json             编号有洞（应校验失败）
      bad-empty.json           空框（应校验失败）
      bad-var.json             未知 ${变量}（应校验失败）
      bad-schema.json          schema_version 不对（应校验失败）
  config.example.json          配置模板（host / user / 密码 / 用哪份 lab）
  config.json                  你的本地配置（不要提交，已在 .gitignore）
  requirements.txt             本机 pip 依赖（Pillow）
  LICENSE                      MIT
  README.md                    本文件
  .gitignore                   忽略 config.json、截图、__pycache__
  shots/                       运行后生成的截图
```

## 各文件干什么

| 路径 | 作用 |
| --- | --- |
| `ScreenshotFucker.py` | 用户只需要碰这个。读配置、提问、校验 JSON、在 Windows 上 SSH 截图；已经在 Linux 实验机上时加 `--on-server`。 |
| `screenshotfucker/__init__.py` | 包标识和版本号 `__version__`。 |
| `screenshotfucker/labfile.py` | 把 `labs/*.json` 变成一串命令。`${role}` 这类变量在这里替换。`--check` / `--list` 也走它。 |
| `screenshotfucker/local.py` | 本机主流程：把 `remote_runner.py` 和实验 JSON 传到 `/tmp/sff_remote.py`、`/tmp/sff_lab.json`，`ssh -tt` 跑起来，看到 `###SFF_SHOT n###` 就截当前窗口。 |
| `screenshotfucker/capture.py` | 按窗口标题找到 conhost，截图，沿粉红条裁掉边界和标题栏。条不在画面里时退回整窗（长输出截开头时会这样）。 |
| `screenshotfucker/consolewin.py` | 把控制台拉高、缓冲区加长、关掉 QuickEdit、截图前把可见区域钉在第一行命令。 |
| `screenshotfucker/sshutil.py` | 补上 OpenSSH 的 PATH；有密码时写临时 ASKPASS；scp 前把 CRLF 改成 LF。 |
| `screenshotfucker/protocol.py` | 本机和远端约定的颜色与标记：`###SFF_SHOT n###`、`###SFF_ACK###`、`SFF_READY`、`SFF_SESSION_OK`。 |
| `screenshotfucker/remote_runner.py` | 由本机上传后只在 Linux 上跑。开真正的 bash PTY，一框打完画三道粉红条，等本机 ACK。 |
| `labs/opengauss-e5.json` | 实验 5 全部灰框，口令、库名、模式都在 `vars` 里。 |
| `labs/example-echo.json` | 不连数据库的冒烟实验，确认 SSH 和截图。 |
| `labs/FORMAT.md` | JSON 字段说明：`script` / `cmds`、`--at` / `--from`。 |
| `config.example.json` | 首次运行时复制为 `config.json`。`host` / `user` / `password` 可留空，程序会提问。 |
| `config.json` | 本机私有配置，含 SSH 目标。不要提交。 |
| `requirements.txt` | 本机只需 Pillow。远端脚本只用 Python 标准库。 |
| `LICENSE` | MIT。 |
| `tests/run_tests.py` | 本地边界测试（不连 SSH）。 |
| `tests/README.md` | 测试覆盖范围说明。 |
| `tests/labs/boundaries.json` | 真机边界：中文、失败后继续、超长输出、超宽行、ANSI、假的 `Password:`。 |
| `tests/labs/at-from.json` | `--at 3` 看不到标记文件；`--from 3` 会回放 1–2 再 cat 出两个标记。 |
| `tests/labs/bad-*.json` | 故意写坏的 JSON，用来确认 `--check` 会拒绝。 |
| `shots/` | 输出目录。`NN.png` 是裁切后的框，`NN_full.png` 是加 `--save-full` 时的整窗。 |

## 最快怎么用

1. `python -m pip install -r requirements.txt`
2. `python ScreenshotFucker.py`
3. 按提示输入实验机地址、SSH 用户、SSH 密码

`config.json` 示例：

```json
{
  "host": "192.168.1.10",
  "user": "root",
  "password": "",
  "lab": "labs/opengauss-e5.json"
}
```

只测截图裁切、不连服务器：

```bat
python ScreenshotFucker.py --shot-test
```

用不连库的两框确认 SSH + 截图：

```bat
python ScreenshotFucker.py --lab labs/example-echo.json
```

已经 SSH 进 Linux 实验机时：

```bash
python3 ScreenshotFucker.py --on-server --lab labs/opengauss-e5.json
```

此时每一框会停下来让你手工截图。自动出 PNG 请在 Windows 上跑本机入口。

## 常用参数

直接 `python ScreenshotFucker.py` 就会按 `config.json` 开跑。需要时再加：

| 参数 | 作用 |
| --- | --- |
| `--lab PATH` | 指定实验 JSON |
| `--config PATH` | 指定配置文件 |
| `--host` `--user` | SSH 目标（覆盖配置） |
| `--from N` | 从第 N 框开始，可能静默回放前面的框 |
| `--at N` | 从第 N 框开始，不执行前面的语句 |
| `--speed 2` | 打字间隔更短 |
| `--shot-dir DIR` | 截图目录 |
| `--save-full` | 额外留一份未裁切的全窗图 |
| `--list` | 只打印灰框 |
| `--check` | 只校验 JSON |
| `--shot-test` | 本机裁切自测 |
| `--on-server` | 在当前 Linux 上跑 |
| `--auto` | 不提问 |
| `--no-relaunch` | 不要再开 conhost |

## 截图是怎么做的

1. 本机把 `screenshotfucker/remote_runner.py` 和实验 JSON 传到实验机 `/tmp/sff_remote.py`、`/tmp/sff_lab.json`
2. `ssh -tt` 在当前窗口里跑远端脚本，你看到的就是真实 bash / gsql
3. 每一框结束，远端画出三道真彩色粉红条（RGB 255,20,147），并打印 `###SFF_SHOT n###`
4. 本机截取标题为 `user@host` 的窗口，沿粉红条裁掉边界，保存 `shots/NN.png`，回 `###SFF_ACK###`
5. 清掉本机控制台缓冲，下一框从顶部开始。输出超高时不往下滚，截图留命令和前几行

若当前是 Windows Terminal，程序会再开一个 `conhost.exe` 窗口，否则粉红条往往截不到像素。

## 自己写实验 JSON

见 [labs/FORMAT.md](labs/FORMAT.md)。最小一框：

```json
{
  "n": 1,
  "title": "hello",
  "script": ["echo hello", "uname -n"]
}
```

要打进终端的数据库口令放在 JSON 的 `vars` 里。SSH 密码只放 `config.json` 或环境变量 `SFF_SSH_PASS`，不要提交。

## 测试

```bat
python tests/run_tests.py
```

## 许可

MIT，见 [LICENSE](LICENSE)。
