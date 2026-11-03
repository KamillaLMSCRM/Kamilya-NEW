"""Batch policy keeps strict JSON on the admitted legacy QA client seam too."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.qa_luna_pending_policy import POLICY as QA_POLICY
from app.modules.ai.v3.revision_policy import POLICY, REVIEW_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus


@pytest.mark.asyncio
@pytest.mark.parametrize('content,code',[
    ('{"rules":[],"rules":[],"document_title":"x","overview":""}','source_first_qa_duplicate_key'),
    ('{"rules":[],"document_title":"x","overview":NaN}','source_first_qa_nonfinite_number'),
])
async def test_batch_policy_rejects_untrusted_qa_raw_json_before_extraction(content,code):
    source='The clerk checks the ticket.'
    document=DirectSourceDocument(str(uuid4()),'Title','source.txt','general','revision',(),source_text=source)
    corpus=DirectSourceCorpus(str(uuid4()),(document,),len(source),0)
    client=SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=content)))
    with pytest.raises(ValueError,match=code):
        await generate_v3_course_from_corpus(corpus,intent=CourseIntent(),generation_client=client,
            revision_policy=POLICY,review_policy=REVIEW_POLICY,authenticated_qa_policy=QA_POLICY)
    assert client.ainvoke.await_count==1
