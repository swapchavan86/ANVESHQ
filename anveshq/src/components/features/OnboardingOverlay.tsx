"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

export function OnboardingOverlay() {
  const [isOpen, setIsOpen] = useState(true);

  if (!isOpen) return null;

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Welcome to the Paperless Trading Engine!</DialogTitle>
          <DialogDescription>
            This is a step-by-step guide to help you get started.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <p>
            <strong>Step 1:</strong> Enter your initial investment amount.
          </p>
          <p>
            <strong>Step 2:</strong> Enter the current market value of your
            investment.
          </p>
          <p>
            <strong>Step 3:</strong> Enter the date you started your
            investment.
          </p>
          <img src="/tutorial.png" alt="Tutorial" />
        </div>
        <DialogFooter>
          <Button onClick={() => setIsOpen(false)}>Get Started</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
