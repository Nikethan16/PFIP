"use client";

import * as React from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ScheduleFARow } from "@/lib/contracts";
import { formatINR, formatISTDate } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";

interface ScheduleFaTableProps {
  rows: ScheduleFARow[];
  // Derived USD peak, if available in future. Display-only.
  usdByRow?: Record<number, number>;
}

/**
 * Schedule FA table: per-country foreign asset disclosure. Columns deliberately
 * match the ITR Schedule FA headings so the user can cross-check line by line.
 *
 * Mobile: rows stack into cards.
 */
export function ScheduleFaTable({ rows, usdByRow }: ScheduleFaTableProps) {
  if (!rows.length) {
    return (
      <EmptyState
        title="No foreign assets yet"
        description="Import INDmoney / Vested / Coinbase to populate this from US or exchange holdings."
      />
    );
  }

  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Country</TableHead>
              <TableHead>Asset</TableHead>
              <TableHead>Acquired</TableHead>
              <TableHead className="text-right">Peak (USD)</TableHead>
              <TableHead className="text-right">Peak (INR)</TableHead>
              <TableHead className="text-right">Closing (INR)</TableHead>
              <TableHead className="text-right">Dividends (INR)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, i) => (
              <TableRow key={`${row.country}-${row.description}-${i}`}>
                <TableCell className="font-medium uppercase">
                  {row.country}
                </TableCell>
                <TableCell>
                  <div>{row.description}</div>
                  <div className="text-xs text-muted-foreground">
                    {row.asset_type}
                  </div>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatISTDate(row.acquired_at)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {usdByRow?.[i] != null
                    ? new Intl.NumberFormat("en-US", {
                        style: "currency",
                        currency: "USD",
                        maximumFractionDigits: 2,
                      }).format(usdByRow[i]!)
                    : "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatINR(row.peak_value_inr)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatINR(row.closing_value_inr)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatINR(row.income_inr)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="grid gap-2 md:hidden">
        {rows.map((row, i) => (
          <div
            key={`${row.country}-${i}`}
            className="rounded-md border bg-card p-3"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{row.description}</span>
              <span className="text-[11px] uppercase text-muted-foreground">
                {row.country}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <div>
                <div className="text-muted-foreground">Peak INR</div>
                <div className="tabular-nums">
                  {formatINR(row.peak_value_inr)}
                </div>
              </div>
              <div>
                <div className="text-muted-foreground">Closing INR</div>
                <div className="tabular-nums">
                  {formatINR(row.closing_value_inr)}
                </div>
              </div>
              <div>
                <div className="text-muted-foreground">Income</div>
                <div className="tabular-nums">{formatINR(row.income_inr)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Acquired</div>
                <div>{formatISTDate(row.acquired_at)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
