package com.acme.support.tools;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

@Service
public class NotificationTools {

    private final JavaMailSender mailSender;

    public NotificationTools(JavaMailSender mailSender) {
        this.mailSender = mailSender;
    }

    @Tool(description = "Send an email to the customer, e.g. to confirm a cancellation")
    public String sendCustomerEmail(String to, String subject, String body) {
        SimpleMailMessage msg = new SimpleMailMessage();
        msg.setFrom("support@acme.example");
        msg.setTo(to);
        msg.setSubject(subject);
        msg.setText(body);
        mailSender.send(msg);
        return "Email sent to " + to;
    }
}
