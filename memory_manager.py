"""
Alliance Terminal Version 3 — RAG Memory Manager
ChromaDB-backed vector database for Commander codex dossier facts.
"""

import logging
import time
import uuid
from pathlib import Path

log = logging.getLogger("normandy.memory")

SCRIPT_DIR = Path(__file__).parent
CHROMA_DIR = str(SCRIPT_DIR / "chroma_db")
COLLECTION_NAME = "commander_dossier"

# Keyword heuristics for auto-categorization
CATEGORY_KEYWORDS = {
    "Preferences": ["prefer", "like", "enjoy", "favor", "love", "hate", "dislike", "rather"],
    "Habits": ["usually", "always", "every day", "routine", "habit", "tend to", "often"],
    "Health": ["allerg", "medic", "health", "diet", "exercise", "sleep", "weight"],
    "Work": ["work", "job", "project", "deadline", "meeting", "colleague", "office"],
    "Schedule": ["schedule", "plan", "appointment", "class", "session", "morning", "evening"],
    "Personal": ["birthday", "family", "friend", "pet", "hobby", "live", "born"],
}

DEFAULT_CATEGORY = "General Intel"


class MemoryManager:
    """Persistent vector memory using ChromaDB for RAG augmentation."""

    def __init__(self):
        self.client = None
        self.collection = None

    def initialize(self):
        """Initialize ChromaDB persistent client and collection."""
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=CHROMA_DIR)
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"description": "Commander N7 personal dossier facts"},
            )
            count = self.collection.count()
            log.info(f"ChromaDB initialized — {count} facts in dossier")
        except Exception as e:
            log.error(f"ChromaDB init failed: {e}")
            raise

    def _infer_category(self, fact: str) -> str:
        """Infer category from fact text using keyword matching."""
        fact_lower = fact.lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in fact_lower:
                    return category
        return DEFAULT_CATEGORY

    def save_fact(self, fact: str, category: str = None) -> str:
        """
        Save a new fact to the dossier with optional category.
        Checks for semantic duplicates before saving.
        """
        if not category:
            category = self._infer_category(fact)

        # --- SEMANTIC DEDUPLICATION CHECK ---
        if self.collection.count() > 0:
            results = self.collection.query(
                query_texts=[fact],
                n_results=1
            )
            # Check the mathematical distance between the text meanings
            if results["distances"] and len(results["distances"][0]) > 0:
                distance = results["distances"][0][0]
                # A distance < 0.3 means it is basically the exact same fact
                if distance < 0.3:
                    log.info(f"Duplicate fact detected (Distance {distance:.2f}). Skipping save.")
                    return None
        # ------------------------------------

        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        self.collection.add(
            ids=[fact_id],
            documents=[fact],
            metadatas=[{"category": category, "timestamp": timestamp}]
        )
        log.info(f"Saved fact '{fact_id}': {fact}")
        return fact_id

    def delete_fact(self, search_text: str) -> bool:
        """Search for a fact containing the text and permanently delete it."""
        try:
            # Grab all documents currently in the database
            results = self.collection.get()
            
            # Scan for a match and delete it by its exact ID
            for doc_id, doc in zip(results['ids'], results['documents']):
                if search_text.lower() in doc.lower():
                    self.collection.delete(ids=[doc_id])
                    return True
            return False
        except Exception as e:
            logging.getLogger("normandy.memory").error(f"Failed to delete fact: {e}")
            return False

    def query_relevant(self, prompt: str, n: int = 5) -> list[str]:
        """Retrieve the most relevant facts for RAG context injection."""
        if self.collection.count() == 0:
            return []

        actual_n = min(n, self.collection.count())
        results = self.collection.query(
            query_texts=[prompt],
            n_results=actual_n,
        )

        facts = results.get("documents", [[]])[0]
        log.info(f"Retrieved {len(facts)} relevant facts for RAG")
        return facts

    def get_all_facts(self) -> list[dict]:
        """Get all facts grouped by category."""
        if self.collection.count() == 0:
            return []

        results = self.collection.get(
            include=["documents", "metadatas"],
        )

        facts = []
        for doc_id, doc, meta in zip(
            results["ids"], results["documents"], results["metadatas"]
        ):
            facts.append({
                "id": doc_id,
                "fact": doc,
                "category": meta.get("category", DEFAULT_CATEGORY),
                "timestamp": meta.get("timestamp", "unknown"),
            })

        facts.sort(key=lambda x: x["timestamp"], reverse=True)
        return facts

    def get_dossier_html(self) -> str:
        """
        Build codex-style HTML dossier with categorized sections.
        Each category gets a styled header with entry count and facts are shown as cards.
        """
        facts = self.get_all_facts()
        if not facts:
            return (
                "<div style='text-align:center; padding:24px; color:#4a6075; "
                "font-family: Montserrat, sans-serif; font-size:11px;'>"
                "No intelligence gathered yet.<br>"
                "Share your preferences and I will build your codex."
                "</div>"
            )

        # Group by category
        categories = {}
        for f in facts:
            cat = f["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f)

        # Define display order and icons
        cat_meta = {
            "Preference": {"icon": "PREF", "color": "#00e5ff"},
            "Preferences": {"icon": "PREF", "color": "#00e5ff"},
            "Habit": {"icon": "HABIT", "color": "#f2a900"},
            "Habits": {"icon": "HABIT", "color": "#f2a900"},
            "Health": {"icon": "HEALTH", "color": "#00ff88"},
            "Academic": {"icon": "ACAD", "color": "#bb86fc"},
            "Work": {"icon": "WORK", "color": "#bb86fc"},
            "Personal": {"icon": "PERS", "color": "#ff6b9d"},
            "Schedule": {"icon": "SCHED", "color": "#f2a900"},
        }
        default_meta = {"icon": "DATA", "color": "#4a6075"}

        cat_order = [
            "Preference", "Preferences", "Health", "Academic", "Work",
            "Habit", "Habits", "Personal", "Schedule",
        ]
        sorted_cats = sorted(
            categories.keys(),
            key=lambda c: cat_order.index(c) if c in cat_order else 99
        )

        html_parts = [
            "<style>"
            ".codex-section { margin-bottom: 8px; }"
            ".codex-hdr { padding: 4px 8px; margin: 0; font-family: Orbitron, sans-serif; "
            "font-size: 9px; font-weight: bold; letter-spacing: 2px; "
            "border-bottom: 1px solid #0a2a44; }"
            ".codex-badge { display: inline; padding: 1px 6px; border-radius: 3px; "
            "font-size: 8px; letter-spacing: 1px; margin-right: 6px; }"
            ".codex-entry { padding: 5px 10px; border-left: 2px solid #0a2a44; "
            "margin: 2px 0 2px 4px; font-family: Montserrat, sans-serif; font-size: 11px; "
            "color: #c8ddf0; }"
            ".codex-ts { font-size: 8px; color: #4a6075; margin-top: 1px; }"
            "</style>"
        ]

        for cat in sorted_cats:
            meta = cat_meta.get(cat, default_meta)
            cat_facts = categories[cat]
            count = len(cat_facts)
            color = meta["color"]

            html_parts.append(
                f"<div class='codex-section'>"
                f"<div class='codex-hdr' style='color:{color};'>"
                f"<span class='codex-badge' style='background:rgba(0,0,0,0.3); "
                f"color:{color}; border:1px solid {color};'>{meta['icon']}</span>"
                f"{cat.upper()} ({count})</div>"
            )

            for f in cat_facts:
                ts = f.get('timestamp', '')
                if ts and len(ts) > 10:
                    ts = ts[:10]  # Just the date
                html_parts.append(
                    f"<div class='codex-entry' style='border-left-color:{color};'>"
                    f"{f['fact']}"
                    f"<div class='codex-ts'>{ts}</div>"
                    f"</div>"
                )

            html_parts.append("</div>")

        return "".join(html_parts)
