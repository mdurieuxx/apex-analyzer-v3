python3 -c '
import json, sys
from datetime import datetime

# Liste ordonnée de tes 3 fichiers source
input_files = [
    "20251115_142905_20251116_005422.jsonl",
    "20251116_005422_20251116_105610.jsonl",
    "20251116_105610_20251118_050340.jsonl"
]
output_file = "agadir_24h_combined_new_format.jsonl"

start_time = None

with open(output_file, "w", encoding="utf-8") as outfile:
    for index, file_name in enumerate(input_files):
        try:
            with open(file_name, "r", encoding="utf-8") as infile:
                # 1. Traitement de la première ligne (métadonnées)
                first_line = infile.readline()
                if not first_line: continue

                old_meta = json.loads(first_line).get("metadata", {})

                # Pour le tout premier fichier, on définit le point zéro global de la course
                if index == 0:
                    start_time_str = old_meta.get("recordingStartTime") or old_meta.get("fileStartTime")
                    if not start_time_str:
                        sys.exit("Impossible de trouver le temps de départ dans le premier fichier.")
                    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))

                    # On écrit l en-tête unique du nouveau format
                    circuit_id = old_meta.get("circuitId", "agadir")
                    new_meta = {
                        "v": 1,
                        "circuit_url": f"https://www.apex-timing.com/live-timing/{circuit_id}/",
                        "ws_port": 8023,
                        "name": old_meta.get("sessionName", "session"),
                        "started_at": start_time_str
                    }
                    outfile.write(json.dumps(new_meta) + "\n")

                # 2. Traitement des lignes de données du fichier en cours
                for line in infile:
                    if not line.strip(): continue
                    row = json.loads(line)
                    if "event" in row: continue

                    current_time_str = row.get("timestamp")
                    msg_data = row.get("data")

                    if current_time_str and msg_data:
                        current_time = datetime.fromisoformat(current_time_str.replace("Z", "+00:00"))

                        # Calcul du delta TOUJOURS par rapport au start_time du premier fichier
                        delta_seconds = (current_time - start_time).total_seconds()

                        # Sécurité pour éviter d enregistrer du bruit de fin de log déconnecté
                        if delta_seconds < 0: continue

                        outfile.write(json.dumps({"t": round(delta_seconds, 3), "msg": msg_data}) + "\n")

            print(f"Fichier traité avec succès : {file_name}")
        except FileNotFoundError:
            print(f"Erreur : Le fichier {file_name} est introuvable.")

print(f"\nFusion et conversion terminées ! -> {output_file}")
'