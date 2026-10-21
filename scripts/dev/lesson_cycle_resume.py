"""Read-only fresh-process DEV checkpoint proof. No generation or data writes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from scripts.dev.lesson_cycle_compare import (
    ROOT,
    TENANT,
    APIClient,
    APIStore,
    save,
    sha,
)


async def run(args):
    env = dotenv_values("C:/Kamilya New/Kamilya-NEW/.env")
    for key, value in env.items():
        if value is not None:
            os.environ[key] = value
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.ai.lesson_cycle import (
        LearningTarget,
        LessonPacket,
        SourceExcerpt,
        run_lesson_cycles,
    )

    receipt = json.loads((args.evidence / "receipt.json").read_text(encoding="utf-8"))
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    assert receipt["tenant_id"] == corpus["tenant_id"] == TENANT and receipt.get(
        "finished_at"
    )
    assert receipt["corpus_sha256"] == sha(corpus)
    relative = "apps/api/app/modules/ai/lesson_cycle.py"
    assert (
        receipt["code_sha256"][relative]
        == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    )
    output = args.evidence / "resume-fresh-process.json"
    assert not output.exists(), "preserve the existing process proof"

    class ReadOnlyAPI(APIClient):
        async def request(self, method, path, **kwargs):
            assert method == "GET", "data-plane mutation forbidden in resume proof"
            return await super().request(method, path, **kwargs)

    class NoModel:
        calls = 0

        async def ainvoke_validated(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("resume must not call a model")

    api, model = ReadOnlyAPI(env, corpus["release_sha"]), NoModel()
    results = []
    try:
        await api.open()
        course = receipt["courses"]["lesson_cycle"]
        live_course = await api.request("GET", "/courses/" + course["id"])
        assert live_course["tenant_id"] == TENANT and live_course["status"] == "draft"
        for case in corpus["cases"]:
            if case["case_id"] not in receipt.get(
                "selected_cases", [c["case_id"] for c in corpus["cases"]]
            ):
                continue
            original = await api.request("GET", "/lessons/" + case["lesson_id"])
            assert (
                original["tenant_id"] == TENANT
                and original["content"] == case["content"]
            )
            packet = LessonPacket(
                TENANT,
                case["lesson_id"],
                case["title"],
                case["content"],
                tuple(SourceExcerpt(**s) for s in case["sources"]),
                tuple(LearningTarget(**t) for t in case["targets"]),
                "paired-" + sha(receipt["provider"]),
            )
            adapter = APIStore(
                api, args.evidence, receipt, course["module_id"], "lesson_cycle"
            )
            result = (await run_lesson_cycles([packet], client=model, store=adapter))[0]
            results.append(
                {
                    "case": case["case_id"],
                    "identity": packet.identity(),
                    "status": result.status,
                    "questions": len(result.questions),
                    "original_unchanged": True,
                    "keys_options_explanations_read_back": True,
                }
            )
        assert model.calls == 0
        proof = {
            "at": datetime.now(UTC).isoformat(),
            "tenant_id": TENANT,
            "qualification": "separate process; local receipt plus server-owned lesson/quiz readback; not a shared-worker checkpoint",
            "model_calls": 0,
            "data_plane_mutations": 0,
            "course_still_draft": True,
            "results": results,
        }
        save(output, proof)
        print(json.dumps(proof, ensure_ascii=False))
    finally:
        await api.client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
