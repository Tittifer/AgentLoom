import { createBrowserRouter, Navigate } from "react-router-dom";

import App from "../App";
import { ColonyListPage } from "../pages/ColonyListPage";
import { ColonyWorkspacePage } from "../pages/ColonyWorkspacePage";
import { QueenListPage } from "../pages/QueenListPage";
import { MemoryLibraryPage } from "../pages/MemoryLibraryPage";
import { SessionWorkspacePage } from "../pages/SessionWorkspacePage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate replace to="/queens" /> },
      { path: "queens", element: <QueenListPage /> },
      { path: "queens/:queenId", element: <ColonyListPage /> },
      { path: "memories", element: <MemoryLibraryPage /> },
      { path: "colonies", element: <Navigate replace to="/queens" /> },
      { path: "colonies/new", element: <Navigate replace to="/queens" /> },
      { path: "colonies/:colonyId", element: <ColonyWorkspacePage /> },
      { path: "sessions/:sessionId", element: <SessionWorkspacePage /> },
      { path: "*", element: <Navigate replace to="/queens" /> },
    ],
  },
]);
