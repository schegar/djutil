import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Library } from "./pages/Library";
import { TrackDetail } from "./pages/TrackDetail";
import { History } from "./pages/History";
import { HistoryDetail } from "./pages/HistoryDetail";
import { Live } from "./pages/Live";
import { Sets } from "./pages/Sets";
import { SetDetail } from "./pages/SetDetail";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Library /> },
      { path: "/live", element: <Live /> },
      { path: "/sets", element: <Sets /> },
      { path: "/sets/:id", element: <SetDetail /> },
      { path: "/tracks/:id", element: <TrackDetail /> },
      { path: "/history", element: <History /> },
      { path: "/history/:id", element: <HistoryDetail /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
