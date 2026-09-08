import { createBrowserRouter, Navigate } from "react-router-dom";

import App from "../App";
import { ColonyWorkspacePage } from "../pages/ColonyWorkspacePage";
import { MemoryLibraryPage } from "../pages/MemoryLibraryPage";
import { SessionWorkspacePage } from "../pages/SessionWorkspacePage";
import { UserSettingsPage } from "../pages/UserSettingsPage";
import { WorkspaceEntryPage } from "../pages/WorkspaceEntryPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <WorkspaceEntryPage /> },
      { path: "queens", element: <Navigate replace to="/" /> },
      { path: "queens/:queenId", element: <Navigate replace to="/" /> },
      { path: "memories", element: <MemoryLibraryPage /> },
      { path: "settings", element: <UserSettingsPage /> },
      { path: "colonies", element: <Navigate replace to="/" /> },
      { path: "colonies/new", element: <Navigate replace to="/" /> },
      { path: "colonies/:colonyId", element: <ColonyWorkspacePage /> },
      { path: "sessions/:sessionId", element: <SessionWorkspacePage /> },
      { path: "*", element: <Navigate replace to="/" /> },
    ],
  },
]);
