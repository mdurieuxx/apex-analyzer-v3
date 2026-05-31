"""
Proposition : gestion des commentaires de course depuis le flux WS Apex.

À intégrer dans apex/client.py — ajouter dans _parse_message() :

    elif msg_type == "comments":
        comments = parse_comments_snapshot(payload)
        self.on_event("comments_snapshot", comments)
    elif msg_type == "com":
        comment = parse_comment(payload)
        if comment:
            self.on_event("comment", comment)

Et broadcaster vers les clients WS frontend via on_apex_event() dans main.py.
"""

import re
from dataclasses import dataclass


# Flags possibles : green, msg, warning, penalty
FLAG_LABELS = {
    "green": "Green flag",
    "msg": "Message",
    "warning": "Avertissement",
    "penalty": "Pénalité",
}


@dataclass
class RaceComment:
    time_str: str          # "HH:MM"
    flag: str              # "green" | "msg" | "warning" | "penalty" | ""
    kart_number: str       # numéro de kart concerné, "" si global
    text: str              # texte du commentaire


def parse_comment(html: str) -> RaceComment | None:
    """
    Parse un message `com||<html>` (payload = la partie HTML).

    Format attendu :
      <p><b>HH:MM</b><span data-flag="TYPE"></span><span class="com_no noN">KART</span>TEXT</p>
    """
    time_m = re.search(r'<b>(\d{1,2}:\d{2})</b>', html)
    flag_m = re.search(r'data-flag="([^"]+)"', html)
    kart_m = re.search(r'class="com_no[^"]*">([^<]+)<', html)

    # Texte = tout le contenu texte sauf les balises
    text = re.sub(r'<[^>]+>', ' ', html).strip()
    text = re.sub(r'\s+', ' ', text)

    # Retirer le time prefix du texte
    if time_m:
        text = text.replace(time_m.group(1), '', 1).strip()
    if kart_m:
        text = text.replace(kart_m.group(1), '', 1).strip()

    if not time_m and not text:
        return None

    return RaceComment(
        time_str=time_m.group(1) if time_m else "",
        flag=flag_m.group(1) if flag_m else "",
        kart_number=kart_m.group(1).strip() if kart_m else "",
        text=text,
    )


def parse_comments_snapshot(html: str) -> list[RaceComment]:
    """
    Parse le snapshot initial `comments||<html>` contenant plusieurs <p>.
    """
    comments = []
    for para in re.findall(r'<p>(.*?)</p>', html, re.DOTALL):
        c = parse_comment(para)
        if c:
            comments.append(c)
    return comments


def comment_to_dict(c: RaceComment) -> dict:
    return {
        "time": c.time_str,
        "flag": c.flag,
        "flag_label": FLAG_LABELS.get(c.flag, c.flag),
        "kart": c.kart_number,
        "text": c.text,
    }
