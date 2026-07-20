import { useState, useEffect, useCallback } from "react";
import { AlertTriangle } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { FormGroup, Input, Textarea, Select } from "../components/ui/FormElements";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { api, formatDate } from "../lib/api";
import type { GrantDecision, Grant, BreakglassStatus } from "../types";

export function Grants() {
  const { showToast } = useToast();

  // Request form state
  const [url, setUrl] = useState("");
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [decision, setDecision] = useState<GrantDecision | null>(null);

  // Active grants
  const [grants, setGrants] = useState<Grant[]>([]);
  const [rateLimitRemaining, setRateLimitRemaining] = useState<number | null>(null);

  // Break glass
  const [breakglass, setBreakglass] = useState<BreakglassStatus | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [triggering, setTriggering] = useState(false);

  const loadGrants = useCallback(async () => {
    try {
      const result = await api.listGrants();
      setGrants(result.active ?? []);
      setRateLimitRemaining(result.rate_limit_remaining ?? null);
    } catch (error) {
      console.error("Failed to load grants:", error);
    }
  }, []);

  const loadBreakglass = useCallback(async () => {
    try {
      const result = await api.getBreakglass();
      setBreakglass(result);
    } catch (error) {
      console.error("Failed to load break-glass status:", error);
    }
  }, []);

  // Initial load + poll every 5 seconds
  useEffect(() => {
    loadGrants();
    loadBreakglass();
    const interval = setInterval(() => {
      loadGrants();
      loadBreakglass();
    }, 5000);
    return () => clearInterval(interval);
  }, [loadGrants, loadBreakglass]);

  const handleRequestGrant = async () => {
    if (!url.trim()) {
      showToast("Please enter a URL", "warning");
      return;
    }
    if (!reason.trim()) {
      showToast("Please provide a reason", "warning");
      return;
    }

    setSubmitting(true);
    setDecision(null);
    try {
      const result = await api.requestGrant(url.trim(), reason.trim(), minutes);
      setDecision(result);
      if (result.decision === "allow") {
        showToast("Access granted", "success");
        await loadGrants();
      } else {
        showToast("Access denied", "error");
      }
    } catch (error) {
      console.error("Failed to request grant:", error);
      showToast("Failed to request grant", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleBreakglass = async () => {
    setConfirmOpen(false);
    setTriggering(true);
    try {
      const result = await api.requestBreakglass();
      setBreakglass(result);
      showToast("Break glass triggered", "warning");
    } catch (error) {
      console.error("Failed to trigger break glass:", error);
      showToast("Failed to trigger break glass", "error");
    } finally {
      setTriggering(false);
    }
  };

  const breakglassState = breakglass?.state ?? "idle";
  const breakglassActive = breakglassState !== "idle";

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-text">Grants</h2>
      </div>

      <div className="grid grid-cols-2 gap-5">
        <Card title="Request Access">
          <FormGroup label="URL">
            <Input
              type="text"
              placeholder="example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={submitting}
            />
          </FormGroup>

          <FormGroup label="Reason">
            <Textarea
              rows={3}
              placeholder="Why do you need access?"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={submitting}
            />
          </FormGroup>

          <FormGroup label="Duration">
            <Select
              value={String(minutes)}
              onChange={(e) => setMinutes(Number(e.target.value))}
              disabled={submitting}
            >
              <option value="15">15 minutes</option>
              <option value="30">30 minutes</option>
              <option value="60">1 hour</option>
              <option value="120">2 hours</option>
            </Select>
          </FormGroup>

          <Button onClick={handleRequestGrant} disabled={submitting} variant="primary">
            {submitting ? "Requesting..." : "Request Access"}
          </Button>

          {decision && (
            <div
              className={`mt-4 p-3 rounded-md text-sm ${
                decision.decision === "allow"
                  ? "bg-success/20 text-success"
                  : "bg-danger/20 text-danger"
              }`}
            >
              {decision.decision === "allow" ? (
                <div>
                  <p className="font-medium">
                    Access granted for {decision.granted_minutes} minutes
                  </p>
                  {decision.expires_at && (
                    <p className="mt-1 text-xs">
                      Expires: {formatDate(decision.expires_at)}
                    </p>
                  )}
                </div>
              ) : (
                <div>
                  <p className="font-medium">Access denied</p>
                  <p className="mt-1 text-xs">{decision.reason}</p>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card title="Active Grants">
          {rateLimitRemaining !== null && (
            <p className="text-xs text-text-secondary mb-4">
              Requests remaining: {rateLimitRemaining}
            </p>
          )}
          {grants.length === 0 ? (
            <p className="text-sm text-text-secondary py-3">
              No active grants.
            </p>
          ) : (
            <ul className="space-y-3">
              {grants.map((grant) => (
                <li
                  key={grant.id}
                  className="p-3 rounded-md bg-bg-secondary border border-border"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-text truncate">
                      {grant.url}
                    </span>
                    <span className="text-xs text-text-secondary shrink-0">
                      {grant.scope}
                    </span>
                  </div>
                  {grant.reason && (
                    <p className="text-xs text-text-secondary mt-1">
                      {grant.reason}
                    </p>
                  )}
                  <p className="text-xs text-text-secondary mt-1">
                    Expires: {formatDate(grant.expires_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Break Glass" className="col-span-2">
          <div className="flex items-start gap-3">
            <AlertTriangle className="text-danger shrink-0 mt-0.5" size={20} />
            <div className="flex-1">
              <p className="text-sm text-text-secondary">
                Break glass is a last resort. It temporarily overrides enforcement
                and is logged. Only use it in a genuine emergency.
              </p>

              {breakglassActive ? (
                <div className="mt-4 p-3 rounded-md bg-danger/20 text-danger text-sm">
                  <p className="font-medium">
                    Break glass state: {breakglassState}
                  </p>
                  {breakglassState === "pending" && breakglass?.release_at && (
                    <p className="mt-1 text-xs">
                      Releases at: {formatDate(breakglass.release_at)}
                    </p>
                  )}
                  {breakglass?.triggered_at && (
                    <p className="mt-1 text-xs">
                      Triggered: {formatDate(breakglass.triggered_at)}
                    </p>
                  )}
                </div>
              ) : (
                <div className="mt-4">
                  <Button
                    onClick={() => setConfirmOpen(true)}
                    disabled={triggering}
                    variant="danger"
                  >
                    {triggering ? "Triggering..." : "Break Glass"}
                  </Button>
                </div>
              )}
            </div>
          </div>
        </Card>
      </div>

      <ConfirmDialog
        isOpen={confirmOpen}
        title="Break glass?"
        message="This is a last resort that overrides enforcement and is logged. Are you sure you want to continue?"
        confirmLabel="Break Glass"
        confirmVariant="danger"
        onConfirm={handleBreakglass}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
