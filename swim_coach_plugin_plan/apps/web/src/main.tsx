import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./app.css";
import { flushFeedbackQueue } from "./offline/feedbackQueue";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing root element");
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js"));
}
window.addEventListener("online", () => void flushFeedbackQueue());

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
