"use client";

import { useSyncExternalStore } from "react";

// Date du jour côté navigateur seulement : null pendant le pré-rendu (avec cacheComponents, un `new Date()` au rendu
// serait figé), puis la date du chargement de la page. Valeur stable entre deux rendus.
let loadedAt: Date | null = null;
const subscribe = () => () => {};

export function useNow(): Date | null {
  return useSyncExternalStore(
    subscribe,
    () => (loadedAt ??= new Date()),
    () => null,
  );
}
