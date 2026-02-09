"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpCircle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { OnboardingOverlay } from "@/components/features/OnboardingOverlay";

export default function SimulatorPage() {
  const [initialValue, setInitialValue] = useState(100000);
  const [currentValue, setCurrentValue] = useState(100000);
  const [entryDate, setEntryDate] = useState("");
  const [netProfit, setNetProfit] = useState(0);

  const calculateProfit = () => {
    const profit = (currentValue - initialValue) * 0.85;
    setNetProfit(profit);
  };

  return (
    <div className="container mx-auto py-10">
      <OnboardingOverlay />
      <h1 className="text-3xl font-bold mb-6">Paperless Trading Engine</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <Card>
          <CardHeader>
            <CardTitle>Investment Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center space-x-2">
              <Input
                type="number"
                value={initialValue}
                onChange={(e) => setInitialValue(parseFloat(e.target.value))}
                placeholder="Initial Investment"
              />
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <HelpCircle className="h-5 w-5 text-gray-500" />
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>The initial amount of your investment.</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            <div className="flex items-center space-x-2">
              <Input
                type="number"
                value={currentValue}
                onChange={(e) => setCurrentValue(parseFloat(e.target.value))}
                placeholder="Current Value"
              />
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <HelpCircle className="h-5 w-5 text-gray-500" />
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>The current market value of your investment.</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            <div className="flex items-center space-x-2">
              <Input
                type="date"
                value={entryDate}
                onChange={(e) => setEntryDate(e.target.value)}
                placeholder="Entry Date"
              />
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <HelpCircle className="h-5 w-5 text-gray-500" />
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>The date you started your investment.</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            <Button onClick={calculateProfit}>Calculate Profit</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Results</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              Net Profit: {netProfit.toFixed(2)} INR
            </p>
          </CardContent>
        </Card>
      </div>
      <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4">How to Use</h2>
        <img src="/tutorial.png" alt="Tutorial" className="w-full" />
      </div>
    </div>
  );
}
