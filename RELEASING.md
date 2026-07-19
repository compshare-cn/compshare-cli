# 发布

GitHub Release 发布后，`.github/workflows/release.yml` 会构建 wheel 和源码包，并通过
PyPI Trusted Publishing 自动上传。仓库不需要保存 PyPI Token。

## 首次配置

在 PyPI 项目 `compshare-cli` 的 Publishing 设置中添加 GitHub Publisher：

| 字段 | 值 |
| --- | --- |
| Owner | `BennielAllan` |
| Repository | `compshare-cli` |
| Workflow | `release.yml` |
| Environment | `pypi` |

## 发布新版本

1. 更新 `src/compshare_cli/__init__.py` 中的版本和 `CHANGELOG.md`。
2. 运行 `ruff check .`、`ruff format --check .` 和 `pytest`。
3. 创建与包版本一致的标签，例如 `v0.2.2`。
4. 发布对应的 GitHub Release。

工作流会校验标签与包版本是否一致，并运行 `twine check`。相同版本不能重复上传到
PyPI；失败时应发布新版本，不能覆盖已有文件。

如果 GitHub Release 早于自动发布工作流，可以在 Actions 中手动运行
`Publish to PyPI`，输入已有的 Release 标签补发。工作流会从该标签构建，避免同一版本
混入标签之后的改动。
