import { createBrowserRouter, Navigate } from "react-router-dom";

import App from "../App";
import { ColonyListPage } from "../pages/ColonyListPage";
import { ColonyWorkspacePage } from "../pages/ColonyWorkspacePage";
import { NewColonyPage } from "../pages/NewColonyPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate replace to="/colonies" /> },
      { path: "colonies", element: <ColonyListPage /> },
      { path: "colonies/new", element: <NewColonyPage /> },
      { path: "colonies/:colonyId", element: <ColonyWorkspacePage /> },
      { path: "*", element: <Navigate replace to="/colonies" /> },
    ],
  },
]);
