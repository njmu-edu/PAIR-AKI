# Third-party software / 第三方来源

| Component | Use | License / source |
| --- | --- | --- |
| Agnes Harness | Actual outer Kernel, session, tool registry, and event ledger | Apache-2.0, [official repository](https://github.com/AgnesAI-Labs/agnes-harness), pin `4bc36bc4c4441206388a53bece17379c1d7be14d`; license/notice in `third_party/` |
| TypeBox | AGH tool schemas | MIT, pinned by `agh/package-lock.json` |
| esbuild | AGH adapter build | MIT, pinned by `agh/package-lock.json` |
| React / React DOM | Workbench | MIT, pinned by `web/package-lock.json` |
| Vite / plugin-react | Frontend tooling | MIT, pinned by `web/package-lock.json` |
| TypeScript | Frontend type checks | Apache-2.0, pinned by `web/package-lock.json` |
| Qwen | Coordinator and research decision-model family | [Qwen3.5-4B model source](https://huggingface.co/Qwen/Qwen3.5-4B); model/adapter weights are not distributed here |

The public application is a portable source release of the PAIR-AKI competition implementation. Core medical-harness modules retain their behavior; private server transports were replaced with configurable local endpoints. Training datasets, private model bundles, runtime logs, and internal documents are not publication inputs.

本仓库为PAIR-AKI竞赛实现的可移植公开源码。医学执行核心保留原行为，私有服务器接线替换为可配置本地接口；不发布训练数据、私有模型包、运行日志或内部文档。AGH上游单独获取并保留原许可，未把其代码改称本项目原创。

The screenshot in `assets/` was captured from a project-owned synthetic demonstration. Synthetic patient identities and values are fabricated test fixtures and do not represent hospital records.

仓库维护、文案及代码整理使用了AI辅助，项目主张和公开范围由团队负责。/ AI assistance was used for repository preparation, writing, and code portability; the team remains responsible for project claims and publication scope.
