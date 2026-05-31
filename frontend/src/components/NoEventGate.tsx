import { Link } from 'react-router-dom'
import { CalendarX, ArrowRight } from 'lucide-react'

export function NoEventGate() {
  return (
    <div className="flex flex-col items-center justify-center h-64 gap-5 text-center">
      <CalendarX size={40} className="text-gray-600" />
      <div>
        <p className="text-gray-300 font-semibold text-base">Aucun événement actif</p>
        <p className="text-gray-500 text-sm mt-1">
          Le live timing est disponible uniquement lorsqu'un événement est activé.
        </p>
      </div>
      <Link
        to="/events"
        className="flex items-center gap-2 bg-orange-600 hover:bg-orange-500 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
      >
        Gérer les événements
        <ArrowRight size={14} />
      </Link>
    </div>
  )
}
