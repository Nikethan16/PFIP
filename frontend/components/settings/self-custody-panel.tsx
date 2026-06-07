"use client";

import * as React from "react";
import { Loader2, Plus, Trash2, Wallet as WalletIcon } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { toast } from "@/components/ui/toast";
import {
  ApiError,
  useAddWallet,
  useDeleteWallet,
  useSelfCustodyWallets,
  useWalletBalances,
  type WalletBalance,
  type WalletChain,
} from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

/**
 * Self-custody wallets manager (Settings).
 *
 * Lists the user's tracked on-chain addresses and lets them add / remove
 * wallets. ADVISORY / TRACKING ONLY — PFIP never holds keys or moves funds; it
 * reads public-chain balances via the ingest flow and shows the latest synced
 * figure. Balances come from `GET /self-custody/wallets/balances`; wallets the
 * ingest flow hasn't synced yet show "syncing…".
 */

const CHAINS: Array<{ value: WalletChain; label: string; placeholder: string }> =
  [
    { value: "btc", label: "BTC", placeholder: "bc1… / 1… / 3…" },
    { value: "eth", label: "ETH", placeholder: "0x… (40 hex)" },
    { value: "sol", label: "SOL", placeholder: "base58 (32–44 chars)" },
  ];

const CHAIN_TINT: Record<string, string> = {
  btc: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  eth: "border-indigo-500/40 bg-indigo-500/10 text-indigo-700 dark:text-indigo-400",
  sol: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
};

/** Middle-truncate a long address for display (keeps head + tail). */
function truncateAddress(addr: string, head = 8, tail = 6): string {
  if (addr.length <= head + tail + 1) return addr;
  return `${addr.slice(0, head)}…${addr.slice(-tail)}`;
}

export function SelfCustodyPanel() {
  const { data: wallets, isLoading, error } = useSelfCustodyWallets();
  // Balances are a superset of wallets (same rows + synced figures). We key
  // off this for display and fall back to the bare wallet list while it loads.
  const { data: balances } = useWalletBalances();
  const addWallet = useAddWallet();
  const deleteWallet = useDeleteWallet();

  const [chain, setChain] = React.useState<WalletChain>("btc");
  const [address, setAddress] = React.useState("");
  const [label, setLabel] = React.useState("");

  // Merge balances onto wallets by id so the list shows synced amounts when
  // available without losing a freshly-added wallet the balances query hasn't
  // picked up yet.
  const byId = React.useMemo(() => {
    const m = new Map<string, WalletBalance>();
    for (const b of balances ?? []) m.set(b.id, b);
    return m;
  }, [balances]);

  const onAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const addr = address.trim();
    if (!addr) {
      toast.error("Enter a wallet address.");
      return;
    }
    try {
      await addWallet.mutateAsync({
        chain,
        address: addr,
        label: label.trim() || null,
      });
      toast.success("Wallet added");
      setAddress("");
      setLabel("");
    } catch (err) {
      // The backend 400s on a bad address and 409s on a duplicate; ProblemSchema
      // can't parse those detail bodies, so message off the status code.
      if (err instanceof ApiError && err.status === 400) {
        toast.error("That doesn't look like a valid address for this chain.");
      } else if (err instanceof ApiError && err.status === 409) {
        toast.error("That address is already tracked for this chain.");
      } else {
        toast.error((err as Error).message);
      }
    }
  };

  const activeChain = CHAINS.find((c) => c.value === chain)!;

  return (
    <div className="space-y-5">
      {/* Advisory note. */}
      <p className="text-[11px] text-muted-foreground">
        Tracking only — PFIP never holds your keys or moves funds. We read public
        on-chain balances and show the latest synced figure. Supported chains:
        BTC, ETH, SOL.
      </p>

      {/* Wallet list. */}
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          Couldn&apos;t load wallets: {(error as Error).message}
        </div>
      ) : !wallets?.length ? (
        <EmptyState
          icon={WalletIcon}
          title="No wallets tracked"
          description="Add a BTC, ETH or SOL address below to track its balance alongside your portfolio."
        />
      ) : (
        <ul className="divide-y divide-border/40 border border-border/50">
          {wallets.map((w) => {
            const bal = byId.get(w.id);
            return (
              <li
                key={w.id}
                className="flex items-center justify-between gap-3 px-4 py-3"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    className={cn(
                      "shrink-0 border px-2 py-0.5 font-label text-[10px] uppercase tracking-wider",
                      CHAIN_TINT[w.chain] ??
                        "border-border/60 bg-secondary/40 text-muted-foreground",
                    )}
                  >
                    {w.chain}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className="truncate font-mono text-xs"
                        title={w.address}
                      >
                        {truncateAddress(w.address)}
                      </span>
                    </div>
                    {w.label ? (
                      <div className="truncate text-[11px] text-muted-foreground">
                        {w.label}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="flex shrink-0 items-center gap-3">
                  <BalanceCell bal={bal} />
                  <button
                    type="button"
                    onClick={() =>
                      deleteWallet.mutate(
                        { id: w.id },
                        {
                          onSuccess: () => toast.success("Wallet removed"),
                          onError: (err) =>
                            toast.error((err as Error).message),
                        },
                      )
                    }
                    disabled={
                      deleteWallet.isPending &&
                      deleteWallet.variables?.id === w.id
                    }
                    className="text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50"
                    aria-label={`Remove ${w.chain} wallet`}
                    title="Remove wallet"
                  >
                    {deleteWallet.isPending &&
                    deleteWallet.variables?.id === w.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Add form. */}
      <form
        onSubmit={onAdd}
        className="grid grid-cols-1 items-end gap-3 border border-border/50 bg-secondary/30 p-4 sm:grid-cols-[6rem_1fr_1fr_auto]"
      >
        <div>
          <Label htmlFor="wallet-chain" className="eyebrow">
            Chain
          </Label>
          <select
            id="wallet-chain"
            value={chain}
            onChange={(e) => setChain(e.target.value as WalletChain)}
            className="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            {CHAINS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="wallet-address" className="eyebrow">
            Address
          </Label>
          <Input
            id="wallet-address"
            placeholder={activeChain.placeholder}
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            className="mt-1 font-mono"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div>
          <Label htmlFor="wallet-label" className="eyebrow">
            Label (optional)
          </Label>
          <Input
            id="wallet-label"
            placeholder="Cold storage"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="mt-1"
          />
        </div>
        <button
          type="submit"
          disabled={addWallet.isPending || !address.trim()}
          className="inline-flex h-10 items-center justify-center gap-2 bg-primary px-4 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110 disabled:opacity-60"
        >
          {addWallet.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          Add
        </button>
      </form>
    </div>
  );
}

/** Right-aligned balance cell: synced amount + unit, or a "syncing…" hint. */
function BalanceCell({ bal }: { bal: WalletBalance | undefined }) {
  if (bal?.synced && bal.balance != null) {
    return (
      <div className="text-right">
        <div className="font-mono text-sm font-semibold tabular-nums">
          {bal.balance.toLocaleString(undefined, {
            maximumFractionDigits: 8,
          })}{" "}
          <span className="text-[10px] uppercase text-muted-foreground">
            {bal.chain}
          </span>
        </div>
        {bal.as_of ? (
          <div className="font-label text-[9px] uppercase tracking-wider text-muted-foreground">
            {formatIST(bal.as_of, "dd MMM")}
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
      syncing…
    </span>
  );
}
