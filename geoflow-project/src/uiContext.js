import { createContext, useContext } from 'react';

/**
 * Actions on the editor as a whole that a node can trigger from inside itself, such as
 * opening the Map tab zoomed to its result. App.jsx provides the real functions.
 */
export const UiContext = createContext({ showOnMap: () => {} });

export const useUi = () => useContext(UiContext);
