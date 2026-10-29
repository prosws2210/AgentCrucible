package com.acme.support.web;

import com.acme.support.tools.NotificationTools;
import com.acme.support.tools.OrderTools;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ChatController {

    public record ChatRequest(String conversationId, String message) {}
    public record ChatReply(String reply) {}

    private final ChatClient chatClient;

    public ChatController(ChatClient.Builder builder, ChatMemory chatMemory,
                          OrderTools orderTools, NotificationTools notificationTools) {
        this.chatClient = builder
                .defaultSystem("You are Acme's order support assistant. Confirm before cancelling anything.")
                .defaultTools(orderTools, notificationTools)
                .defaultAdvisors(MessageChatMemoryAdvisor.builder(chatMemory).build())
                .build();
    }

    @PostMapping("/chat")
    public ChatReply chat(@RequestBody ChatRequest request) {
        String answer = chatClient.prompt()
                .user(request.message())
                .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, request.conversationId()))
                .call()
                .content();
        return new ChatReply(answer);
    }
}
