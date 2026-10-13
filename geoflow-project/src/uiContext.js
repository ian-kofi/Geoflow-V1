import { createContext, useContext } from 'react';

/** Editor-level UI actions that nodes can trigger, e.g. opening the Map tab on an area. */
export const UiContext = createContext({ showOnMap: () => {} });

export const useUi = () => useContext(UiContext);
