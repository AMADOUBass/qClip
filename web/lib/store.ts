"use client";

// État local de l'interface (Zustand) : palette de commandes, VOD et moment courants.

import { create } from "zustand";

type UiState = {
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
};

export const useUi = create<UiState>((set) => ({
  paletteOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
}));
