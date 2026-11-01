"""A factual report cannot manufacture a medical label or candidate identity."""
from .state import factual_view


def build(snapshot, outcomes, handled, errors, limits):
    prediction_result = handled.get("event_prediction", {})
    comparison_result = handled.get("comparable_cases", {})
    prediction = prediction_result.get("prediction")
    comparables = comparison_result.get("comparables")
    evidence = [{"ref": "snapshot:" + snapshot.snapshot_ref, "kind": "state", "source_kind": snapshot.source_kind}]
    evidence += [{"ref": row["ref"], "kind": "observation", "source_kind": snapshot.source_kind} for row in snapshot.observations]
    statements = []
    if prediction is not None:
        ref = "prediction:" + snapshot.snapshot_ref
        evidence.append({"ref": ref, "kind": "prediction", "source_kind": snapshot.source_kind})
        label = prediction["label"]
        text = f"24小时研究事件预测：{label}。" + ("模型预测目标时间窗内发生该事件。" if label == 1 else "模型预测目标时间窗内不发生该事件。")
        if prediction["receipt"]["mode"] == "synthetic":
            text = f"合成工具回执：{label}；此值用于工程验证，不是已训练医学模型的结果。"
        statements.append({"id": "prediction", "text": text, "evidence_refs": [ref]})
    if comparables is not None:
        ref = "index:" + comparables["index_sha256"]
        evidence.append({"ref": ref, "kind": "reference_index", "source_kind": snapshot.source_kind})
        statements.append({"id": "comparables", "text": f"获得{len(comparables['matches'])}名不同患者的可比病例参考。", "evidence_refs": [ref]})
        for i, candidate in enumerate(comparables["matches"]):
            ref = "snapshot:" + candidate["snapshot_ref"]
            evidence.append({"ref": ref, "kind": "reference_state", "source_kind": candidate["source_kind"]})
            evidence += [{"ref": r, "kind": "reference_observation", "source_kind": candidate["source_kind"]} for r in candidate["evidence_refs"]]
            shared = "、".join(r["label"] for r in candidate["similarities"][:2])
            differences = "、".join(r["label"] for r in candidate["differences"][:2])
            statements.append({"id": f"reference-{i}", "text": f"参考{i+1}的相近维度：{shared}；应核对的差异：{differences}。",
                               "evidence_refs": [ref]})
    for outcome in outcomes:
        result = handled.get(outcome)
        if result and result["status"] == "blocked":
            limits.append(outcome + ": " + result["reason"])
        elif outcome in errors:
            limits.append(outcome + ": 工具失败，未返回合格医学结果。")
        elif not result:
            limits.append(outcome + ": 本次执行未完成该项。")
    limits.append("端点为首次合格肌酐事件，不等于完整临床AKI诊断。")
    if snapshot.source_kind == "synthetic":
        limits.append("本次使用明确合成病例，只用于工程验证。")
    modes = ([prediction["receipt"]["mode"]] if prediction else []) + ([r["mode"] for r in comparables["receipts"]] if comparables else [])
    if "synthetic" in modes:
        limits.append("本次医学工具回执来自合成提供器，不代表两个新模型已训练。")
    for i, text in enumerate(dict.fromkeys(limits)):
        statements.append({"id": f"limit-{i}", "text": text, "evidence_refs": ["snapshot:" + snapshot.snapshot_ref]})
    return {"prediction": prediction, "comparables": comparables, "narrative": statements,
            "evidence": list({r["ref"]: r for r in evidence}.values()), "limitations": list(dict.fromkeys(limits)),
            "final_snapshot": factual_view(snapshot)}
