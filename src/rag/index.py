"""Requirement 색인: 등록된 모든 버전을 파싱하고 Chroma에 넣는다.

- Requirement 1개 = 청크 1개. 메타데이터: ID, 제목, 시트, 영역, 버전, 범위.
- 청크 본문에는 AWS 원문만 넣는다. internal_note(담당자 한글 메모)는 넣지 않는다(영문 답변 유출 방지).
- 다시 실행하면 컬렉션을 지우고 새로 만든다(같은 입력 → 같은 색인).

실행: python -m src.rag.index
"""
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src import config
from src.assessment import parser
from src.llm import get_embeddings

COLLECTION = "assessment_requirements"


def get_vectorstore() -> Chroma:
    """색인 저장소(Chroma)를 연다."""
    return Chroma(
        persist_directory=str(config.CHROMA_DIR),
        embedding_function=get_embeddings(),
        collection_name=COLLECTION,
    )


def to_document(req: dict) -> Document:
    """Requirement 하나를 검색용 문서로 만든다(내부 메모 제외)."""
    header = f"[{req['id']}] {req['title']}\nSheet: {req['sheet']}"
    if req.get("area"):
        header += f"\nArea: {req['area']}"
    return Document(
        page_content=f"{header}\n\n{req['text']}",
        metadata={
            "id": req["id"],
            "title": req["title"],
            "sheet": req["sheet"],
            "area": req.get("area") or "",
            "scope": req["scope"],
            "version": req["version"],
        },
    )


def build_index() -> dict[str, int]:
    """모든 버전을 파싱하고 색인한다. 반환: {버전: 문서 수}."""
    parsed = parser.build_all()
    store = get_vectorstore()
    store.reset_collection()  # 이전 색인 삭제 후 다시 만든다
    counts = {}
    for label, data in parsed.items():
        docs = [to_document(r) for r in data["requirements"]]
        store.add_documents(docs, ids=[f"{label}:{d.metadata['id']}" for d in docs])
        counts[label] = len(docs)
    return counts


if __name__ == "__main__":
    for label, n in build_index().items():
        print(f"indexed {label}: {n} requirements")
    print(f"-> {config.CHROMA_DIR} (collection: {COLLECTION})")
