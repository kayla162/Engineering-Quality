import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import DemoApp from "./demo/DemoApp";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* VITE_DEMO=1 建置成靜態展示版：只有搜尋與問 AI，資料來自 public/demo-data.json */}
    {import.meta.env.VITE_DEMO === "1" ? <DemoApp /> : <App />}
  </StrictMode>,
);
