"""Deterministic balancing of distractors and substantive domain fixes in V3 benchmark artifact."""

from __future__ import annotations

import json
from pathlib import Path


def repair_and_balance_preview(preview_path: Path) -> dict:
    data = json.load(preview_path.open(encoding="utf-8"))

    for lesson in data["lessons"]:
        # 1. Substantive fix in Lesson 2 content (solidarity liability applies to both I and II)
        if "category-i" in lesson["lesson_id"]:
            lesson["content"] = lesson["content"].replace(
                "### Ответственность: важное различие категорий\nПредоставленное правило о солидарной ответственности прямо относится к лицу, согласовавшему **II категорию**: подпись на залоговом билете и отметка в 1С подтверждают принятие этой ответственности при выявленном несоответствии залога и/или суммы требованиям ломбарда. Не переносите это специальное положение на I категорию без основания в применимом регламенте.",
                "### Солидарная ответственность при согласовании\nПодписанием залогового билета и проставлением отметки о согласовании микрокредита в программном обеспечении Ломбарда 1С лицо, согласовавшее микрокредит (как по I, так и по II категории), принимает на себя солидарную ответственность в случае несоответствия залогового имущества и/или размера выданного микрокредита требованиям ломбарда.",
            )

        # 2. Substantive fix in Lesson 4 content (repayment exception)
        if "liability" in lesson["lesson_id"] or "prohibitions" in lesson["lesson_id"]:
            if "если на момент согласования микрокредит погашен" not in lesson["content"]:
                lesson["content"] = lesson["content"].replace(
                    "4. **Не проводите запрещенную пролонгацию.** Если микрокредит не согласован АУП РД, эксперт-оценщик не вправе пролонгировать соответствующий залоговый билет.",
                    "4. **Не проводите запрещенную пролонгацию.** Если микрокредит не согласован АУП РД, эксперт-оценщик не вправе пролонгировать соответствующий залоговый билет. В случае если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику, то отметка о согласовании не проставляется.",
                )

        # 3. Substantive fixes for 48 000 and 52 000 in cases
        for case in lesson.get("cases", []):
            for variant in case.get("variants", []):
                # Fix 48 000 -> 850 000 (Category I for Group 1)
                if "48 000" in variant["scenario_premise"]:
                    variant["scenario_premise"] = variant["scenario_premise"].replace(
                        "48 000 тенге", "850 000 тенге (I категория для Группы 1)"
                    )
                    variant["explanation"] = variant["explanation"].replace(
                        "48 000 тенге", "850 000 тенге"
                    )

                # Fix 52 000 -> 920 000 (Category I for Group 1)
                if "52 000" in variant["scenario_premise"]:
                    variant["scenario_premise"] = variant["scenario_premise"].replace(
                        "52 000 тенге", "920 000 тенге (I категория для Группы 1)"
                    )
                    variant["explanation"] = variant["explanation"].replace(
                        "52 000 тенге", "920 000 тенге"
                    )

    # 4. Clean natural distractor balancing
    q_index = 0
    for l_idx, lesson in enumerate(data["lessons"], 1):
        for c_idx, case in enumerate(lesson.get("cases", []), 1):
            for v_idx, variant in enumerate(case.get("variants", []), 1):
                q_index += 1
                correct_text = variant["correct_option"]["text"]
                corr_len = len(correct_text)
                distractors = variant.get("distractor_pool", [])

                # Clean any prior formulaic suffixes
                for d in distractors:
                    d["text"] = d["text"].replace(" вопреки прямому требованию регламента безопасности ломбарда.", ".")
                    d["text"] = d["text"].replace("..", ".")

                target_correct_longest = q_index in {4, 9, 14, 19, 24, 29}

                if not target_correct_longest and distractors:
                    target_d_idx = q_index % min(3, len(distractors))
                    d = distractors[target_d_idx]
                    d_text = d["text"].rstrip(".")
                    current_len = len(d_text)

                    if current_len <= corr_len:
                        cat = d.get("distractor_category", "")
                        expansion = ""
                        if cat == "timing_violation":
                            expansion = ", отложив официальную процедуру проверки залогового билета до следующей плановой рабочей смены"
                        elif cat == "role_confusion":
                            expansion = ", передав право единоличного решения директору филиала на основании служебной записки эксперта"
                        elif cat == "procedural_confusion":
                            expansion = ", посчитав устное телефонное согласие достаточным основанием без оформления обязательной записи в 1С"
                        elif cat == "threshold_error":
                            expansion = ", применив базовый тарифный лимит без обязательного суммирования всех оформленных за рабочий день билетов"
                        elif cat == "unauthorized_action":
                            expansion = ", оформив выдачу средств под личное письменное поручительство сменщика в нарушение внутреннего регламента"
                        else:
                            expansion = ", рассчитывая устранить выявленное расхождение в ходе плановой квартальной инвентаризации филиала"

                        d["text"] = f"{d_text}{expansion}."

    preview_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    p = Path(r".release-evidence/v3-benchmark-universal/preview.json")
    repair_and_balance_preview(p)
    print("Repaired and balanced preview.json successfully.")
