import React from "react";
import ReactDOM from "react-dom/client";
import { ThemeProvider } from "./providers/theme-provider";
import App from "./App";
import "./styles/globals.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="light" storageKey="dataif.theme">
      <App />
    </ThemeProvider>
  </React.StrictMode>
);
