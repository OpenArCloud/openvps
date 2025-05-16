/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import "./globals.css";
import "allotment/dist/style.css";

export const metadata = {
  title: "Map Aligner",
  description: "Point cloud transform calculator",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="m-0">{children}</body>
    </html>
  );
}
