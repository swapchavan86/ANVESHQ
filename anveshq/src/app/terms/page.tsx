export default function TermsPage() {
  return (
    <div className="bg-white py-16 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
          Terms of Use
        </h1>
        <p className="mt-6 text-lg text-gray-500">
          Last Updated: {new Date().toLocaleDateString()}
        </p>

        <div className="mt-12 prose prose-indigo max-w-none">
          <h2>1. Acceptance of Terms</h2>
          <p>
            By accessing and using the ANVESHQ platform (the "Service"), you
            accept and agree to be bound by the terms and provision of this
            agreement. In addition, when using this Service, you shall be
            subject to any posted guidelines or rules applicable to such
            services. Any participation in this service will constitute
            acceptance of this agreement. If you do not agree to abide by the
            above, please do not use this service.
          </p>

          <h2>2. Market Data Disclaimer</h2>
          <p>
            The data and information provided by ANVESHQ are for informational
            purposes only and should not be relied upon for trading purposes.
            All data is sourced from third-party providers and is not
            guaranteed to be accurate, complete, or timely. ANVESHQ and its
            data providers shall not be liable for any errors or delays in the
            content, or for any actions taken in reliance thereon.
          </p>

          <h2>3. No Investment Advice</h2>
          <p>
            ANVESHQ is a decision-support tool and does not provide investment
            advice. The information, analysis, and tools provided on this
            platform are not intended to be a recommendation to buy, sell, or
            hold any security. You are solely responsible for your own
            investment decisions and should consult with a qualified financial
            advisor before making any investment.
          </p>

          <h2>4. User Responsibility</h2>
          <p>
            You are responsible for your use of the Service and for any
            decisions made based on the information provided. You agree to use
            the Service in compliance with all applicable laws and regulations.
            You are responsible for maintaining the confidentiality of your
            account and password, if applicable.
          </p>

          <h2>5. Limitation of Liability</h2>
          <p>
            In no event shall ANVESHQ, its officers, directors, employees, or
            agents, be liable to you for any direct, indirect, incidental,
            special, punitive, or consequential damages whatsoever resulting
            from any (i) errors, mistakes, or inaccuracies of content, (ii)
            personal injury or property damage, of any nature whatsoever,
            resulting from your access to and use of our Service, (iii) any
unauthorized access to or use of our secure servers and/or any and
            all personal information and/or financial information stored
            therein.
          </p>

          <h2>6. Data Accuracy</h2>
          <p>
            While we strive to provide accurate and up-to-date information, we
            make no warranty or representation regarding the accuracy,
            completeness, or reliability of any data or information on the
            Service. The information is provided "as is" without any warranty
            of any kind.
          </p>
          
          <h2>7. Changes to Terms</h2>
          <p>
            ANVESHQ reserves the right to modify these terms from time to time
            at our sole discretion. Therefore, you should review these pages
            periodically. Your continued use of the Service after any such
            change constitutes your acceptance of the new Terms.
          </p>
        </div>
      </div>
    </div>
  );
}