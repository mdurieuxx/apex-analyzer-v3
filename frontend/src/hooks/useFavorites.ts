import { useState, useCallback } from 'react'

const STORAGE_KEY = 'karting_favorites'

function load(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch {
    return new Set()
  }
}

function save(s: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...s]))
}

export function useFavorites() {
  const [favorites, setFavorites] = useState<Set<string>>(load)

  const toggle = useCallback((driverId: string) => {
    setFavorites(prev => {
      const next = new Set(prev)
      if (next.has(driverId)) {
        next.delete(driverId)
      } else {
        next.add(driverId)
      }
      save(next)
      return next
    })
  }, [])

  return { favorites, toggle }
}
