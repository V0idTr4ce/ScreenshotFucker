# 测试

本地（不连 SSH）：

```
python tests/run_tests.py
```

覆盖 JSON 校验、`${变量}`、`--at` 与 `--from` 不能同时用、gsql 等待推断、粉红条裁切、剩条、以及不能把整行亮色文本当成标题栏。

真机实验 JSON：

- `tests/labs/boundaries.json`：中文、失败后继续、超长输出、超宽行、ANSI、假的 `Password:`
- `tests/labs/at-from.json`：`--at 3` 看不到标记文件；`--from 3` 会回放 1–2 再 cat 出两个标记
