export default function PrivacyPage() {
  return (
    <div className="bg-white py-16 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
          Privacy Policy
        </h1>
        <p className="mt-6 text-lg text-gray-500">
          Last Updated: {new Date().toLocaleDateString()}
        </p>

        <div className="mt-12 prose prose-indigo max-w-none">
          <h2>1. Introduction</h2>
          <p>
            ANVESHQ ("we", "our", "us") is committed to protecting and
            respecting your privacy. This Privacy Policy explains how we
            collect, use, and share information about you when you use our
            platform and services (the "Service").
          </p>

          <h2>2. Information We Collect</h2>
          <p>We may collect and process the following data about you:</p>
          <ul>
            <li>
              <strong>Information you provide to us:</strong> This includes
              information you provide when you register for an account, create
              a watchlist, or contact us for support, such as your name and
              email address.
            </li>
            <li>
              <strong>Information we collect automatically:</strong> When you
              use our Service, we automatically collect information about your
              device and your usage of our Service, including your IP address,
              browser type, operating system, and information about the pages
              you visit.
            </li>
          </ul>

          <h2>3. Cookies and Analytics</h2>
          <p>
            We use cookies and similar tracking technologies to track the
            activity on our Service and hold certain information. Cookies are
            files with a small amount of data which may include an anonymous
            unique identifier. We use this information to improve our Service
            and provide a better user experience. We may also use third-party
            analytics services like Google Analytics to assist us in analyzing
            how our Service is used.
          </p>

          <h2>4. How We Use Your Information</h2>
          <p>We use the information we collect for various purposes:</p>
          <ul>
            <li>To provide, maintain, and improve our Service.</li>
            <li>To manage your account and provide you with customer support.</li>
            <li>
              To monitor the usage of our Service and analyze trends.
            </li>
            <li>
              To personalize your experience on our Service.
            </li>
          </ul>

          <h2>5. Data Protection and Security</h2>
          <p>
            We take the security of your data seriously. We use appropriate
            technical and organizational measures to protect your personal
          information from unauthorized access, use, or disclosure. However,
            no method of transmission over the Internet or method of electronic
            storage is 100% secure.
          </p>

          <h2>6. We Do Not Sell Your Personal Data</h2>
          <p>
            ANVESHQ is committed to maintaining your trust. We do not and will
            not sell your personal information to third parties. Your privacy is
            a fundamental part of our mission.
          </p>

          <h2>7. Your Rights</h2>
          <p>
            Depending on your location, you may have certain rights regarding
            your personal information, including the right to access, correct,
            or delete your data. If you wish to exercise these rights, please
            contact us at{" "}
            <a href="mailto:privacy@anveshq.com">privacy@anveshq.com</a>.
          </p>
          
          <h2>8. Changes to This Privacy Policy</h2>
          <p>
            We may update our Privacy Policy from time to time. We will notify
            you of any changes by posting the new Privacy Policy on this page.
            You are advised to review this Privacy Policy periodically for any
            changes.
          </p>
        </div>
      </div>
    </div>
  );
}