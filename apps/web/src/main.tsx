import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { SessionGate } from "./SessionGate";
import "./base.css";
import "./workspace.css";

if (import.meta.env.DEV) void import("./styles.css");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {import.meta.env.DEV ? <App /> : <SessionGate />}
  </React.StrictMode>,
);
