import { createBrowserRouter, Navigate } from "react-router-dom";

import App from "../App";
import { NewTaskPage } from "../pages/NewTaskPage";
import { RunDetailPage } from "../pages/RunDetailPage";
import { TaskDetailPage } from "../pages/TaskDetailPage";
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
      {
        path: "tasks/new",
        element: <NewTaskPage />,
      },
      {
        path: "tasks/:taskId",
        element: <TaskDetailPage />,
      },
      {
        path: "runs/:runId",
        element: <RunDetailPage />,
      },
    ],
  },
]);
