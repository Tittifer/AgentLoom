import { createBrowserRouter, Navigate } from "react-router-dom";

import App from "../App";
import { TaskListPage } from "../pages/TaskListPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      {
        index: true,
        element: <Navigate replace to="/tasks" />,
      },
      {
        path: "tasks",
        element: <TaskListPage />,
      },
    ],
  },
]);
