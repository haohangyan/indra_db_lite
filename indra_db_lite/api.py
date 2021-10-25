import re
from contextlib import closing
import json
import sqlite3
from typing import Collection, Dict, List, Iterator, Optional, Tuple, Union

from indra_db_lite.locations import INDRA_DB_LITE_LOCATION


__all__ = [
    "get_entrez_pmids",
    "get_entrez_pmids_for_hgnc",
    "get_entrez_pmids_for_uniprot",
    "get_paragraphs_for_text_ref_ids",
    "get_plaintexts_for_text_ref_ids",
    "get_pmids_for_text_ref_ids",
    "get_taxon_id_for_uniprot",
]


def _filter_paragraphs(
        paragraphs: List[int],
        contains: Optional[Union[List[str], str]] = None
):
    """Filter paragraphs to only those containing one of a list of strings

    Parameters
    ----------
    paragraphs : list of str
        List of plaintext paragraphs from an article

    contains : str or list of str
        Exclude paragraphs not containing this string as a token, or
        at least one of the strings in contains if it is a list

    Returns
    -------
    str
        Plaintext consisting of all input paragraphs containing at least
        one of the supplied tokens.
    """
    if contains is None:
        pattern = ''
    else:
        if isinstance(contains, str):
            contains = [contains]
        pattern = '|'.join(r'(^|[^\w])%s([^\w]|$)' % re.escape(shortform)
                           for shortform in contains)
    paragraphs = [p for p in paragraphs if re.search(pattern, p)]
    return '\n'.join(paragraphs) + '\n'


class TextContent:
    __slots__ = ['fulltexts', 'abstracts', 'titles', 'processed']

    def __init__(
            self, content_rows: Iterator[Tuple[int, str, List[str]]]
    ) -> None:
        self.processed: bool = False
        self.fulltexts: Dict[int, Union[List[str], str]] = {}
        self.abstracts: Dict[int, Union[List[str], str]] = {}
        self.titles: Dict[int, Union[List[str], str]] = {}
        for text_ref_id, text_type, content in content_rows:
            content = json.loads(content)
            if text_type == 'fulltext':
                self.fulltexts[text_ref_id] = content
            if text_type == 'abstract':
                self.abstracts[text_ref_id] = content
            if text_type == 'title':
                self.titles[text_ref_id] = content

    def __len__(self) -> int:
        return len(self.fulltexts) + len(self.abstracts) + len(self.titles)

    def flatten(self) -> Dict[int, Union[List[str], str]]:
        """Flatten text content irrespective of text_type

        Returns a single dictionary mapping text_ref_ids to content
        """
        result = {}
        result.update(self.fulltexts)
        result.update(self.abstracts)
        result.update(self.titles)
        return result

    def to_plaintexts(self, contains: Optional[str] = None) -> None:
        if self.processed:
            return
        fulltexts = {
            text_ref_id: _filter_paragraphs(paragraphs, contains=contains)
            for text_ref_id, paragraphs in self.fulltexts.items()
        }
        self.fulltexts = {
            text_ref_id: text for text_ref_id, text in fulltexts.items()
            if len(text) > 1
        }
        abstracts = {
            text_ref_id: _filter_paragraphs(paragraphs, contains=contains)
            for text_ref_id, paragraphs in self.abstracts.items()
        }
        self.abstracts = {
            text_ref_id: text for text_ref_id, text in abstracts.items()
            if len(text) > 1
        }
        titles = {
            text_ref_id: _filter_paragraphs(paragraphs, contains=contains)
            for text_ref_id, paragraphs in self.titles.items()
        }
        self.titles = {
            text_ref_id: text for text_ref_id, text in titles.items()
            if len(text) > 1
        }
        self.processed = True

    def __str__(self):
        return (
            f"TextContent({len(self.fulltexts)} fulltexts,"
            f" {len(self.abstracts)} abstracts,"
            f" {len(self.titles)} titles)"
        )

    def __repr__(self):
        return str(self)


def get_paragraphs_for_text_ref_ids(
        text_ref_ids: Collection[int]
) -> TextContent:
    text_ref_ids = tuple(text_ref_ids)
    query = f"""SELECT
                text_ref_id, text_type, content
            FROM
                best_content
            WHERE
                text_ref_id IN ({','.join(['?']*len(text_ref_ids))})
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            rows = (
                tuple(row) for row in cur.execute(
                    query, text_ref_ids
                ).fetchall()
            )
    return TextContent(rows)


def get_plaintexts_for_text_ref_ids(
        text_ref_ids: Collection[int],
        contains: Optional[Union[List[str], str]] = None,
) -> TextContent:
    content = get_paragraphs_for_text_ref_ids(text_ref_ids)
    content.to_plaintexts(contains=contains)
    return content


def get_text_ref_ids_for_pmids(
        pmids: Collection[int]
) -> Dict[int, int]:
    pmids = tuple(pmids)
    query = f"""--
    SELECT
        pmid, text_ref_id
    FROM
        pmid_text_refs
    WHERE
        pmid IN ({','.join(['?']*len(pmids))})
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            pmid_text_refs = cur.execute(query, pmids).fetchall()
    return {
        pmid: text_ref_id for pmid, text_ref_id in pmid_text_refs
    }


def get_pmids_for_text_ref_ids(
        text_ref_ids: Collection[int]
) -> Dict[int, int]:
    text_ref_ids = tuple(text_ref_ids)
    query = f"""--
    SELECT
        text_ref_id, pmid
    FROM
        pmid_text_refs
    WHERE
        text_ref_id IN ({','.join(['?']*len(text_ref_ids))}) AND
        pmid IS NOT NULL
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            text_ref_pmids = cur.execute(query, text_ref_ids).fetchall()
    return {
        text_ref_id: pmid for text_ref_id, pmid in text_ref_pmids
    }


def get_text_ref_ids_for_agent_text(agent_text: str) -> List[int]:
    query = """--
    SELECT
        text_ref_id
    FROM
        agent_texts
    WHERE
        agent_text = ?;
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, (agent_text, )).fetchall()
    return [row[0] for row in res]


def get_entrez_pmids_for_hgnc(hgnc_id: str) -> List[int]:
    query = """--
    SELECT
        pmid
    FROM
        entrez_pmids
    WHERE
        hgnc_id = ?;
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, (hgnc_id, )).fetchall()
    return [row[0] for row in res]


def get_entrez_pmids_for_uniprot(uniprot_id: str) -> List[int]:
    query = """--
    SELECT
        pmid
    FROM
        entrez_pmids
    WHERE
        uniprot_id = ?;
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, (uniprot_id, )).fetchall()
    return [row[0] for row in res]


def get_entrez_pmids(entrez_id: int) -> List[int]:
    query = """--
    SELECT
        pmid
    FROM
        entrez_pmids
    WHERE
        entrez_id = ?;
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, (entrez_id, )).fetchall()
    return [row[0] for row in res]


def get_taxon_id_for_uniprot(uniprot_id: int) -> int:
    query = """--
    SELECT
        taxon_id
    FROM
        entrez_pmids
    WHERE
        uniprot_id = ?;
    """
    with closing(sqlite3.connect(INDRA_DB_LITE_LOCATION)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, (uniprot_id, )).fetchall()
    return res[0][0]
