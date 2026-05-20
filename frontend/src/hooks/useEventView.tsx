import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

interface Ctx {
  viewedEventId: number | null
  viewedEventName: string
  setViewed: (id: number | null, name: string) => void
}

const EventViewContext = createContext<Ctx>({
  viewedEventId: null,
  viewedEventName: '',
  setViewed: () => {},
})

export function EventViewProvider({ children }: { children: ReactNode }) {
  const [viewedEventId, setViewedEventId] = useState<number | null>(null)
  const [viewedEventName, setViewedEventName] = useState('')

  function setViewed(id: number | null, name: string) {
    setViewedEventId(id)
    setViewedEventName(name)
  }

  return (
    <EventViewContext.Provider value={{ viewedEventId, viewedEventName, setViewed }}>
      {children}
    </EventViewContext.Provider>
  )
}

export function useEventView() {
  return useContext(EventViewContext)
}
