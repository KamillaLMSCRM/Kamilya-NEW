"""Conversion-owned, non-authoritative source proposals."""
import hashlib
from collections.abc import Mapping


def extract_review_only_candidates(metadata: object, source_sha: str) -> tuple[dict[str, str], ...]:
    if not isinstance(metadata, Mapping):
        return ()
    candidates = metadata.get('review_only_source_composites')
    if candidates is None:
        return ()
    if not isinstance(candidates, list) or len(candidates) > 16:
        raise ValueError('review_only_source_composites_invalid')
    accepted=[]
    for item in candidates:
        if not isinstance(item, Mapping):
            raise ValueError('review_only_source_composites_invalid')
        text=item.get('composite_text')
        if (item.get('status')!='review_only' or item.get('semantic_authority') is not False
                or item.get('source_sha256')!=source_sha or not isinstance(text,str)
                or not text.strip() or len(text)>4096
                or hashlib.sha256(text.encode('utf-8')).hexdigest()!=item.get('composite_sha256')):
            raise ValueError('review_only_source_composites_invalid')
        accepted.append({'text':text,'source_sha256':source_sha,'composite_sha256':item['composite_sha256']})
    return tuple(accepted)


def has_review_only_unresolved(metadata: object, source_sha: str) -> bool:
    if not isinstance(metadata, Mapping) or metadata.get('review_only_source_unresolved') is None:
        return False
    receipt=metadata['review_only_source_unresolved']
    if (not isinstance(receipt, Mapping) or receipt.get('source_sha256') != source_sha
            or not isinstance(receipt.get('issues'), list) or not 1 <= len(receipt['issues']) <= 16
            or any(not isinstance(issue, Mapping) or not isinstance(issue.get('reason'), str)
                or not issue['reason'] or len(issue['reason']) > 128 for issue in receipt['issues'])):
        raise ValueError('review_only_source_unresolved_invalid')
    return True
