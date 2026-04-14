import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { slugify } from "@/lib/slugify";

const SLUG_PATTERN = /^[a-z0-9_-]+$/;

export interface PromptField {
  name: string;
  label: string;
  placeholder?: string;
  defaultValue?: string;
  type?: "text" | "password";
  required?: boolean;
  monospace?: boolean;
  autoSlugFrom?: string;
  slugSeparator?: "_" | "-";
  pattern?: RegExp;
  patternHint?: string;
}

interface PromptDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  fields: PromptField[];
  submitLabel?: string;
  cancelLabel?: string;
  onSubmit: (values: Record<string, string>) => Promise<void> | void;
}

export function PromptDialog({
  open,
  onOpenChange,
  title,
  description,
  fields,
  submitLabel,
  cancelLabel,
  onSubmit,
}: PromptDialogProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      const initial: Record<string, string> = {};
      for (const f of fields) initial[f.name] = f.defaultValue ?? "";
      setValues(initial);
      setTouched({});
      setSubmitting(false);
    }
  }, [open, fields]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => firstFieldRef.current?.focus(), 50);
    return () => window.clearTimeout(timer);
  }, [open]);

  function updateField(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
    setTouched((prev) => ({ ...prev, [name]: true }));
  }

  function effectiveValue(field: PromptField): string {
    const raw = values[field.name] ?? "";
    if (field.autoSlugFrom && !touched[field.name]) {
      const source = values[field.autoSlugFrom] ?? "";
      return slugify(source, field.slugSeparator ?? "_");
    }
    return raw;
  }

  function effectivePattern(field: PromptField): RegExp | null {
    if (field.pattern) return field.pattern;
    if (field.autoSlugFrom) return SLUG_PATTERN;
    return null;
  }

  function fieldError(field: PromptField): "empty" | "pattern" | null {
    const value = effectiveValue(field);
    if (!value) return (field.required ?? true) ? "empty" : null;
    const pattern = effectivePattern(field);
    if (pattern && !pattern.test(value)) return "pattern";
    return null;
  }

  const canSubmit = useMemo(
    () => fields.every((f) => fieldError(f) === null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fields, values, touched],
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    const resolved: Record<string, string> = {};
    for (const f of fields) resolved[f.name] = effectiveValue(f);

    setSubmitting(true);
    try {
      await onSubmit(resolved);
      onOpenChange(false);
    } catch {
      // Caller is expected to surface the error via its own state; keep dialog open.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description ? (
              <DialogDescription>{description}</DialogDescription>
            ) : (
              <DialogDescription className="sr-only">
                {title}
              </DialogDescription>
            )}
          </DialogHeader>

          <div className="space-y-4">
            {fields.map((field, index) => {
              const value = effectiveValue(field);
              const error = fieldError(field);
              const showPatternError =
                touched[field.name] && error === "pattern";
              const hint =
                field.patternHint ??
                (field.autoSlugFrom ? t("common.invalid_slug") : undefined);
              return (
                <div key={field.name} className="flex flex-col gap-1.5">
                  <Label htmlFor={`prompt-field-${field.name}`}>
                    {field.label}
                  </Label>
                  <Input
                    id={`prompt-field-${field.name}`}
                    ref={index === 0 ? firstFieldRef : undefined}
                    type={field.type ?? "text"}
                    value={value}
                    onChange={(e) => updateField(field.name, e.target.value)}
                    placeholder={field.placeholder}
                    aria-invalid={showPatternError || undefined}
                    className={cn(
                      field.monospace && "font-mono text-[12px]",
                      showPatternError &&
                        "border-destructive focus-visible:ring-destructive/30 focus-visible:border-destructive",
                    )}
                  />
                  {showPatternError && hint && (
                    <p className="text-[11px] text-destructive">{hint}</p>
                  )}
                </div>
              );
            })}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              {cancelLabel ?? t("common.cancel")}
            </Button>
            <Button type="submit" disabled={submitting || !canSubmit}>
              {submitLabel ?? t("common.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
