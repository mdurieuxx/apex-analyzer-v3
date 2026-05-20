import json
from datetime import datetime

input_file = "20251019_073928_20251019_160408.jsonl"
output_file = "20251019_converted_to_new_format.jsonl"

with open(input_file, "r", encoding="utf-8") as infile, open(output_file, "w", encoding="utf-8") as outfile:
    # 1. Lire la première ligne de l'ancien fichier (les métadonnées complexes)
    first_line = infile.readline()
    if not first_line:
        exit("Le fichier est vide.")

    old_data = json.loads(first_line)
    old_meta = old_data.get("metadata", {})

    # Récupération du temps de départ pour calculer les deltas 't'
    # On privilégie 'fileStartTime' ou 'recordingStartTime'
    start_time_str = old_meta.get("fileStartTime") or old_meta.get("recordingStartTime")
    if not start_time_str:
        exit("Impossible de trouver le temps de départ dans les métadonnées.")

    # Nettoyage pour le parsing (remplacement du 'Z' par le décalage UTC si nécessaire)
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))

    # Reconstruction de la première ligne au NOUVEAU format
    # On mappe les anciennes métadonnées sur la nouvelle structure plate
    new_meta = {
        "v": 1,
        "circuit_url": f"https://www.apex-timing.com/live-timing/{old_meta.get('circuitId', 'mariembourg')}/",
        "ws_port": 8313,  # Valeur par défaut d'Apex si non spécifiée explicitement
        "name": old_meta.get("sessionName", "session"),
        "started_at": start_time_str
    }
    outfile.write(json.dumps(new_meta) + "\n")

    # 2. Convertir toutes les lignes suivantes
    for line in infile:
        if not line.strip():
            continue
        row = json.loads(line)

        # On ignore les lignes d'événements réseau (comme CONNECTED) qui n'existent pas dans le nouveau format
        if "event" in row:
            continue

        # Extraction du timestamp et des données de timing
        current_time_str = row.get("timestamp")
        msg_data = row.get("data")

        if current_time_str and msg_data:
            current_time = datetime.fromisoformat(current_time_str.replace("Z", "+00:00"))

            # Calcul du delta en secondes (flottant)
            delta_seconds = (current_time - start_time).total_seconds()

            # Reconstruction au nouveau format : {"t": ..., "msg": ...}
            # On arrondit à 3 décimales pour correspondre aux millisecondes du nouveau format
            new_row = {
                "t": round(delta_seconds, 3),
                "msg": msg_data
            }
            outfile.write(json.dumps(new_row) + "\n")

print(f"Conversion vers le nouveau format terminée ! Fichier sauvegardé sous : {output_file}")